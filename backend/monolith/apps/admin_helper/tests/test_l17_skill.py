"""Plan L17: the skill files, their generated pasted form, and the console's two buttons."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.admin_helper import actions, skill, views
from apps.admin_panel.permissions import AdminRole
from apps.admin_panel.tests.two_step_helpers import staff_login

from .test_l15_keys import PAGES
from .world import make_staff

#: What every assistant must be told, as the server words it. The skill names
#: only these few fields; `guide` carries the rest (plan L17 content rules).
NAMED_FIELDS = ("next_step", "confirm_url", "untrusted_user_text")
KEY_SHAPE = re.compile(r"wsl[rw]_[A-Za-z0-9_-]{20,}")


class SkillFilesTests(SimpleTestCase):
    def test_the_pasted_instructions_are_generated_from_the_skill(self):
        assert skill.INSTRUCTIONS_FILE.read_text(encoding="utf-8") == skill.instructions_text()
        call_command("build_helper_instructions", "--check", stdout=io.StringIO())

    def test_the_check_fails_when_the_file_is_out_of_date(self):
        original = skill.INSTRUCTIONS_FILE.read_text(encoding="utf-8")
        try:
            skill.INSTRUCTIONS_FILE.write_text(original + "\nstale", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("build_helper_instructions", "--check", stdout=io.StringIO())
        finally:
            skill.INSTRUCTIONS_FILE.write_text(original, encoding="utf-8")

    def test_the_core_file_is_short_and_in_the_standard_layout(self):
        text = skill.skill_md()
        assert len(text.splitlines()) <= skill.SKILL_MAX_LINES
        front = text.split("---\n", 2)[1]
        assert "name: wassla\n" in front
        assert re.search(r"^description: .{20,}$", front, re.MULTILINE)
        assert skill.skill_body().startswith("# ")

    def test_no_file_holds_a_key_or_an_address(self):
        for path in [skill.SKILL_DIR / "SKILL.md", *skill.knowledge_files()]:
            text = path.read_text(encoding="utf-8")
            assert not KEY_SHAPE.search(text), path.name
            assert not re.search(r"https?://(?!\.\.\.)[a-z0-9.-]+\.[a-z]{2,}/api/admin", text), path.name
        assert not KEY_SHAPE.search(skill.instructions_text())

    def test_every_knowledge_file_is_named_by_the_core_file_and_has_its_header(self):
        files = skill.knowledge_files()
        assert files, "the skill needs its knowledge files"
        core = skill.skill_md()
        for path in files:
            assert f"knowledge/{path.name}" in core, f"SKILL.md never points at {path.name}"
            lines = path.read_text(encoding="utf-8").splitlines()
            assert lines[0].startswith("# "), path.name
            assert any(line.startswith("Covers: ") for line in lines[:4]), path.name
            assert "UNSURE:" not in "\n".join(lines), f"{path.name} still has an open UNSURE"
            related = next((line for line in lines[:6] if line.startswith("Related files:")), "")
            for name in re.findall(r"[\w-]+\.md", related):
                assert (skill.KNOWLEDGE_DIR / name).exists(), f"{path.name} relates to a missing {name}"
        for name in re.findall(r"knowledge/([\w.-]+\.md)", core):
            assert (skill.KNOWLEDGE_DIR / name).exists(), f"SKILL.md names a missing file: {name}"

    def test_the_core_file_names_the_real_endpoints_and_fields(self):
        core = skill.skill_md()
        for endpoint in ("guide", "briefing", "tasks", "queues/", "records/", "search?q=", "actions"):
            assert endpoint in core, endpoint
        from apps.admin_helper import prepared, resources

        source = "".join(
            Path(module.__file__).read_text(encoding="utf-8") for module in (views, actions, prepared, resources)
        )
        for name in NAMED_FIELDS:
            assert name in core, name
            assert name in source, f"{name} is no longer in the helper"

    def test_the_zip_is_the_skill_folder(self):
        names = set(zipfile.ZipFile(io.BytesIO(skill.skill_zip())).namelist())
        assert "wassla/SKILL.md" in names
        assert {f"wassla/knowledge/{path.name}" for path in skill.knowledge_files()} <= names
        assert not any(name.endswith("INSTRUCTIONS.txt") for name in names)


@override_settings(**PAGES)
class SkillConsoleTests(TestCase):
    def setUp(self):
        self.admin = make_staff("skill-admin@example.test", AdminRole.SUPPORT)
        self.client = Client()
        staff_login(self.client, self.admin)

    def test_the_card_has_both_buttons(self):
        page = self.client.get(reverse("admin_console:overview")).content.decode()
        assert "Download the skill" in page and "Copy the instructions" in page
        assert reverse("admin_console:ai-helper-skill") in page
        assert reverse("admin_console:ai-helper-instructions") in page

    def test_the_download_is_the_zip_built_from_the_files(self):
        response = self.client.get(reverse("admin_console:ai-helper-skill"))
        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        assert "attachment" in response["Content-Disposition"]
        assert "no-store" in response["Cache-Control"]
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert archive.read("wassla/SKILL.md").decode() == skill.skill_md()

    def test_the_copy_text_is_the_generated_instructions(self):
        response = self.client.get(reverse("admin_console:ai-helper-instructions"))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")
        assert response.content.decode() == skill.instructions_text()

    def test_only_get_and_only_signed_in_staff(self):
        for name in ("ai-helper-skill", "ai-helper-instructions"):
            url = reverse(f"admin_console:{name}")
            assert self.client.post(url).status_code == 405
            assert Client().get(url).status_code in (301, 302, 403)


class DealPaymentLinkTests(TestCase):
    """The assistant prepares a refund on a payment: the deal record must lead to it."""

    def test_the_deal_record_links_its_payments_by_the_admins_rights(self):
        from apps.admin_helper.models import AdminHelperKey  # noqa: F401

        from .world import bearer, build_world, new_key

        world = build_world("l17")
        for role, opens in ((AdminRole.SUPER_ADMIN, True), (AdminRole.SUPPORT, False)):
            admin = make_staff(f"{role}-l17@example.test", role)
            response = Client().get(f"/api/admin/helper/v1/records/deal/{world.deal.pk}", **bearer(new_key(admin)))
            assert response.status_code == 200
            (link,) = response.json()["payments"]
            assert link["type"] == "payment" and link["id"] == world.payment.pk
            assert (link["console_url"] is not None) is opens
            assert (link["record"] is not None) is opens

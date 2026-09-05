"""Build a normalized Phase 8B manifest from official geography downloads.

The script deliberately keeps network access explicit (``--download``) and
uses a fixed allow-list of authoritative hosts. Django imports the resulting
JSON with ``manage.py import_geography``; no bulk data is embedded in a
migration.  The Algeria coordinate/name JSON is supplemental only: its
identity and hierarchy are accepted after reconciliation with JORADP Law
26-06 (F2026025.pdf), and the generated manifest records that provenance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
import urllib.request
from urllib.parse import urlparse
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


YEAR = "2026"
EXPECTED_SELECTABLE_AIRPORTS = {"DZ": 31, "FR": 49, "ES": 42, "DE": 39}
DOWNLOADS = {
    "algeria_official": "https://www.joradp.dz/FTP/jo-francais/2026/F2026025.pdf",
    "algeria_ons": "https://www.ons.dz/IMG/pdf/code_geo_2021.pdf",
    "france": "https://www.insee.fr/fr/statistiques/fichier/8740222/cog_ensemble_2026_csv.zip",
    "spain": "https://www.ine.es/daco/daco42/codmun/26codmun.xlsx",
    "germany": "https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/Archiv/GVAuszugQ/AuszugGV2QAktuell.xlsx?__blob=publicationFile&v=13",
    "airports": "https://ourairports.com/data/airports.csv",
    "algeria_wilayas": "https://raw.githubusercontent.com/riadh2002/algeria-69-wilayas-1541-communes/main/data/wilayas.json",
    "algeria_communes": "https://raw.githubusercontent.com/riadh2002/algeria-69-wilayas-1541-communes/main/data/communes.json",
}
ALLOWED_HOSTS = {
    "www.insee.fr",
    "www.ine.es",
    "www.destatis.de",
    "ourairports.com",
    "raw.githubusercontent.com",
    "www.joradp.dz",
    "www.ons.dz",
}
XML_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Law 26-06 rewrites the commune membership of ten mother wilayas and adds
# eleven new wilayas. The importer extracts these article bodies from the
# official JORADP PDF; none of the legal commune lists is duplicated here.
JORADP_ARTICLE_WILAYAS = {
    "7": 3,
    "9": 5,
    "11": 7,
    "16": 12,
    "17": 13,
    "18": 14,
    "21": 17,
    "30": 26,
    "32": 28,
    "36": 32,
    "52 bis 10": 59,
    "52 bis 11": 60,
    "52 bis 12": 61,
    "52 bis 13": 62,
    "52 bis 14": 63,
    "52 bis 15": 64,
    "52 bis 16": 65,
    "52 bis 17": 66,
    "52 bis 18": 67,
    "52 bis 19": 68,
    "52 bis 20": 69,
}
NEW_WILAYA_MOTHER = {
    59: 3,
    60: 5,
    61: 7,
    62: 12,
    63: 13,
    64: 14,
    65: 17,
    66: 17,
    67: 26,
    68: 28,
    69: 32,
}

# The supplemental coordinate file still carries several pre-law or abbreviated
# labels. These are explicit reconciliations to the canonical names printed in
# JORADP Law 26-06, never inferred translations.
OFFICIAL_NAME_ALIASES = {
    "benacer ben chohra": "Benacer Benchohra",
    "ain mahdi": "Aïn Madhi",
    "tadjmout": "Tadjemout",
    "el kheneg": "Kheneg",
    "el haouaita": "El Haouita",
    "el madher": "Elmadher",
    "ngaous": "N’Gaous",
    "inoughissen": "Inoughissene",
    "ouled selam": "Ouled Sellem",
    "beni foudhala el hakania": "Béni Fedhala El Hakania",
    "tkout": "T’Kout",
    "zanat el beida": "Zana El Beïda",
    "mchouneche": "M’Chounèche",
    "m ziraa": "Meziraa",
    "el hadjab": "El Hadjeb",
    "khanguet sidinadji": "Khangat Sidi Nadji",
    "bir el mokadem": "Bir Mokkadem",
    "bir dheb": "Bir Dheheb",
    "gorriguer": "Gourrigueur",
    "el ma el biodh": "El Ma Labiod",
    "tlidjene": "Thlidjene",
    "el mazeraa": "El Mezeraa",
    "oued chouly": "Oued Lakhdar",
    "sebbaa chioukh": "Sebaa Chioukh",
    "terni beni hediel": "Tirni Béni Hediel",
    "marsa ben mhidi": "Marsa Ben M’Hidi",
    "souk el khemis": "Béni Khellad",
    "ain zarit": "Aïn Dzarit",
    "ouled djerad": "Djebilet Rosfa",
    "djillali ben amar": "Djileli Ben Amar",
    "oued lilli": "Oued Lili",
    "mechraa safa": "Mechraa Sfa",
    "moudjebara": "Moudjbara",
    "el guedid": "El Gueddid",
    "dar chouikh": "Dar Chioukh",
    "beni yacoub": "Ben Yaagoub",
    "el guelbelkebir": "El Guelb El Kebir",
    "mezerena": "Mezghenna",
    "tamesguida": "Tamezguida",
    "el azizia": "Al Azizia",
    "tlatet eddouair": "Eddouair",
    "sidi errabia": "Sidi Errabie",
    "bir ben laabed": "Bir Ben Abed",
    "khams djouamaa": "Khamsa Djoumaa",
    "msila": "M’Sila",
    "mtarfa": "M’Tarfa",
    "khettouti sed djir": "Khetouti Sed  El Djir",
    "bougtoub": "Bougtob",
    "sidi ameur": "Sidi Amar",
    "beidha": "El Beïdha",
    "metkaouak": "Abdelkader Azil",
    "m doukel": "M’Doukal",
    "djemorah": "Djemourah",
    "el ogla": "El Ogla El Melha",
    "zmalet el emir aek": "Zmalet El Emir Abdelkader",
    "serghine": "Serguine",
    "bouira lahdeb": "Bouira Lahdab",
    "ain oussera": "Aïn Ouessara",
    "feidh el botma": "Faïdh El Botma",
    "oum el djalil": "Oum El Djallil",
    "meftaha": "M’Fatha",
    "oued chair": "Mouhamed Boudiaf",
    "ouled atia": "Menaâ",
    "sidi mhamed": "Sidi M’Hamed",
    "ain el melh": "Aïn El Meleh",
    "oultene": "Oultem",
    "el mehara": "El Meharra",
}

# The coordinate supplement uses these spellings for nine communes that were
# already assigned codes 49-58 by the official 2021 ONS CGN. They are exact,
# reviewed reconciliations, used only to locate the corresponding ONS row.
ONS_NAME_ALIASES = {
    "tabalbala": "TABELBALA",
    "ech chaiba": "CHAIBA",
    "ouled khoudir": "OULED KHODEIR",
    "tinzaouatine": "TIN ZAOUATINE",
    "balidat ameur": "BLIDAT AMEUR",
    "mnaguer": "M'NAGUAR",
    "mrara": "M'RARA",
    "sidi khellil": "SIDI KHELIL",
    "el mghair": "EL MEGAIER",
    "hassi gara": "HASSI EL GARA",
}

SPAIN_AUTONOMOUS_COMMUNITIES = {
    "AN": ("01", "Andalucía"),
    "AR": ("02", "Aragón"),
    "AS": ("03", "Principado de Asturias"),
    "IB": ("04", "Illes Balears"),
    "CN": ("05", "Canarias"),
    "CB": ("06", "Cantabria"),
    "CL": ("07", "Castilla y León"),
    "CM": ("08", "Castilla-La Mancha"),
    "CT": ("09", "Cataluña"),
    "VC": ("10", "Comunitat Valenciana"),
    "EX": ("11", "Extremadura"),
    "GA": ("12", "Galicia"),
    "MD": ("13", "Comunidad de Madrid"),
    "MC": ("14", "Región de Murcia"),
    "NC": ("15", "Comunidad Foral de Navarra"),
    "PV": ("16", "País Vasco"),
    "RI": ("17", "La Rioja"),
    "CE": ("18", "Ceuta"),
    "ML": ("19", "Melilla"),
}
SPAIN_PROVINCE_COMMUNITY = {
    "01": "PV",
    "02": "CM",
    "03": "VC",
    "04": "AN",
    "05": "CL",
    "06": "EX",
    "07": "IB",
    "08": "CT",
    "09": "CL",
    "10": "EX",
    "11": "AN",
    "12": "VC",
    "13": "CM",
    "14": "AN",
    "15": "GA",
    "16": "PV",
    "17": "CT",
    "18": "AN",
    "19": "CM",
    "20": "PV",
    "21": "AN",
    "22": "AR",
    "23": "AN",
    "24": "CL",
    "25": "CT",
    "26": "RI",
    "27": "GA",
    "28": "MD",
    "29": "AN",
    "30": "MC",
    "31": "NC",
    "32": "GA",
    "33": "AS",
    "34": "CL",
    "35": "CN",
    "36": "GA",
    "37": "CL",
    "38": "CN",
    "39": "CB",
    "40": "CL",
    "41": "AN",
    "42": "CL",
    "43": "CT",
    "44": "AR",
    "45": "CM",
    "46": "VC",
    "47": "CL",
    "48": "PV",
    "49": "CL",
    "50": "AR",
    "51": "CE",
    "52": "ML",
}
FRANCE_ISO_REGION_TO_INSEE = {
    "ARA": "84",
    "BFC": "27",
    "BRE": "53",
    "CVL": "24",
    "COR": "94",
    "GES": "44",
    "HDF": "32",
    "IDF": "11",
    "NOR": "28",
    "NAQ": "75",
    "OCC": "76",
    "PDL": "52",
    "PAC": "93",
}
GERMANY_ISO_STATE_TO_DESTATIS = {
    "SH": "01",
    "HH": "02",
    "NI": "03",
    "HB": "04",
    "NW": "05",
    "HE": "06",
    "RP": "07",
    "BW": "08",
    "BY": "09",
    "SL": "10",
    "BE": "11",
    "BR": "12",
    "MV": "13",
    "SN": "14",
    "ST": "15",
    "TH": "16",
}


def _name_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).casefold()
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _pdf_reader(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - operator environment guard
        raise RuntimeError(
            "PDF source parsing requires: pip install -r tools/geography/requirements.txt"
        ) from exc
    return PdfReader(path)


def _parse_joradp_assignments(path: Path) -> dict[int, list[str]]:
    """Extract all Law 26-06 mother/new-wilaya commune assignments."""

    text = "\n".join((page.extract_text() or "") for page in _pdf_reader(path).pages)
    assignments: dict[int, list[str]] = {}
    for article, wilaya_code in JORADP_ARTICLE_WILAYAS.items():
        if article.startswith("52 bis "):
            article_pattern = rf"52\s*\.?\s*[Bb]is\s+{article.rsplit(' ', 1)[1]}"
        else:
            article_pattern = re.escape(article)
        start_match = re.search(
            rf"«\s*Art\.\s*{article_pattern}\.\s*—\s*Les\s+.+?\((\d+)\)\s+communes\s+suivantes",
            text,
            flags=re.DOTALL,
        )
        if start_match is None:
            raise ValueError(f"JORADP Law 26-06 article {article} was not found")
        next_article = text.find("« Art.", start_match.end())
        block = text[start_match.end() : next_article if next_article >= 0 else None]
        names = [
            match.group(1).strip()
            for match in re.finditer(
                r"(?m)^\s*\d+\.\s+(.+?)(?:\s*;\s*$|\.\s*»\.\s*$)",
                block,
            )
        ]
        expected_count = int(start_match.group(1))
        if len(names) != expected_count:
            raise ValueError(
                f"JORADP article {article} contains {expected_count} communes, "
                f"but {len(names)} were extracted"
            )
        assignments[wilaya_code] = names
    return assignments


def _parse_ons_communes(path: Path) -> dict[str, dict[str, str]]:
    """Extract the 2021 official ONS CGN W/C identities from its PDF."""

    communes: dict[str, dict[str, str]] = {}
    for page in _pdf_reader(path).pages[3:]:
        for line in (page.extract_text() or "").splitlines():
            match = re.match(
                r"^\s*(.+?)\s+(\d{2})\s+(\d{2})(?:\s+.*)?$",
                line.strip(),
            )
            if match is None or "Commune" in match.group(1) or "Code" in match.group(1):
                continue
            official_id = f"{match.group(2)}{match.group(3)}"
            if official_id in communes:
                raise ValueError(f"Duplicate ONS CGN commune code {official_id}")
            communes[official_id] = {
                "name": match.group(1).strip(),
                "wilaya_code": match.group(2),
                "commune_code": match.group(3),
            }
    if len(communes) != 1541:
        raise ValueError(
            f"ONS CGN 2021 must contain 1541 commune codes; found {len(communes)}"
        )
    return communes


def _download(url: str, target: Path) -> None:
    host = urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing non-allow-listed source host: {host}")
    request = urllib.request.Request(
        url, headers={"User-Agent": "ShipTrip-geography-import/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - allow-list above
        target.write_bytes(response.read())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_zip(archive: zipfile.ZipFile, target: Path) -> None:
    """Extract a reviewed source archive without permitting path traversal."""

    target = target.resolve()
    members = archive.infolist()
    if sum(member.file_size for member in members) > 500_000_000:
        raise ValueError("Refusing geography archive larger than 500 MB unpacked")
    for member in members:
        destination = (target / member.filename).resolve()
        if destination != target and target not in destination.parents:
            raise ValueError(f"Refusing unsafe archive member: {member.filename}")
        archive.extract(member, target)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.iter(f"{{{XML_NS['m']}}}t"))
        for item in root.findall("m:si", XML_NS)
    ]


def _xlsx_rows(
    archive: zipfile.ZipFile, filename: str, shared: list[str]
) -> Iterable[list[str]]:
    root = ET.fromstring(archive.read(filename))
    for row in root.findall(".//m:row", XML_NS):
        values: dict[int, str] = {}
        for cell in row.findall("m:c", XML_NS):
            ref = cell.attrib.get("r", "")
            match = re.match(r"([A-Z]+)", ref)
            if not match:
                continue
            column = 0
            for char in match.group(1):
                column = column * 26 + ord(char) - ord("A") + 1
            raw = cell.find("m:v", XML_NS)
            if raw is None:
                inline = cell.find("m:is", XML_NS)
                value = (
                    ""
                    if inline is None
                    else "".join(
                        node.text or "" for node in inline.iter(f"{{{XML_NS['m']}}}t")
                    )
                )
            elif cell.attrib.get("t") == "s":
                value = shared[int(raw.text)]
            else:
                value = raw.text or ""
            values[column] = value
        if values:
            yield [values.get(index, "") for index in range(1, max(values) + 1)]


def _country(
    code: str, name: str, source: str, source_id: str, version: str
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "source": source,
        "source_id": source_id,
        "source_version": version,
        "active": True,
    }


def _place(
    *,
    source: str,
    source_id: str,
    version: str,
    country: str,
    place_type: str,
    name: str,
    parent_source_id: str | None = None,
    parent_source: str | None = None,
    admin_level: str = "",
    latitude: Any = None,
    longitude: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source": source,
        "source_id": str(source_id),
        "source_version": version,
        "country_code": country,
        "place_type": place_type,
        "name": name,
        "admin_level": admin_level,
        "active": True,
    }
    if parent_source_id is not None:
        row["parent_source_id"] = str(parent_source_id)
        row["parent_source"] = parent_source or source
    if latitude not in (None, "") and longitude not in (None, ""):
        row["latitude"] = latitude
        row["longitude"] = longitude
    row.update(extra)
    return row


def parse_france(path: Path, manifest: dict[str, Any]) -> None:
    version = "INSEE-COG-2026"
    source_dir = path.with_suffix("")
    if not source_dir.exists():
        source_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            _extract_zip(archive, source_dir)
    commune_file = source_dir / "v_commune_2026.csv"
    region_file = source_dir / "v_region_2026.csv"
    department_file = source_dir / "v_departement_2026.csv"
    countries = manifest["countries"]
    countries.append(_country("FR", "France", "insee-country", "FR", version))
    regions: dict[str, dict[str, Any]] = {}
    with region_file.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            code = row["REG"]
            name = row.get("LIBELLE") or row.get("NCCENR") or row["NCC"]
            regions[code] = _place(
                source="insee-cog-region",
                source_id=code,
                version=version,
                country="FR",
                place_type="admin_region",
                name=name,
                admin_level="region",
            )
    manifest["places"].extend(regions.values())
    departments: dict[str, dict[str, Any]] = {}
    with department_file.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            code = row["DEP"]
            name = row.get("LIBELLE") or row.get("NCCENR") or row["NCC"]
            departments[code] = _place(
                source="insee-cog-department",
                source_id=code,
                version=version,
                country="FR",
                place_type="admin_region",
                name=name,
                parent_source_id=row["REG"],
                parent_source="insee-cog-region",
                admin_level="department",
            )
    manifest["places"].extend(departments.values())
    with commune_file.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("TYPECOM") != "COM":
                continue
            name = row.get("LIBELLE") or row.get("NCCENR") or row["NCC"]
            manifest["places"].append(
                _place(
                    source="insee-cog-commune",
                    source_id=row["COM"],
                    version=version,
                    country="FR",
                    place_type="locality",
                    name=name,
                    parent_source_id=row["DEP"],
                    parent_source="insee-cog-department",
                    admin_level="commune",
                    metadata={"official_code": row["COM"], "region_code": row["REG"]},
                )
            )
            alternate = row.get("NCCENR") or row.get("NCC")
            if alternate and alternate != name:
                manifest["alternate_names"].append(
                    {
                        "place_source": "insee-cog-commune",
                        "place_source_id": row["COM"],
                        "name": alternate,
                        "language": "fr",
                        "source": "insee-cog-commune-alt",
                        "source_id": f"{row['COM']}:fr",
                        "source_version": version,
                    }
                )


def parse_spain(path: Path, manifest: dict[str, Any]) -> None:
    version = "INE-REL-2026-01-01"
    source = "ine-municipality"
    manifest["countries"].append(_country("ES", "Spain", "ine-country", "ES", version))
    for _, (community_code, community_name) in SPAIN_AUTONOMOUS_COMMUNITIES.items():
        manifest["places"].append(
            _place(
                source="ine-autonomous-community",
                source_id=community_code,
                version=version,
                country="ES",
                place_type="admin_region",
                name=community_name,
                admin_level="autonomous_community",
            )
        )
    with zipfile.ZipFile(path) as archive:
        shared = _xlsx_shared_strings(archive)
        sheets = sorted(
            (
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            ),
            key=lambda value: int(re.search(r"sheet(\d+)", value).group(1)),
        )
        seen_provinces: set[str] = set()
        for sheet in sheets:
            rows = list(_xlsx_rows(archive, sheet, shared))
            province_name = rows[1][0] if len(rows) > 1 and rows[1] else "Province"
            for row in rows[3:]:
                if len(row) < 4 or not row[0] or not row[1] or not row[3]:
                    continue
                province, municipality, check_digit, name = row[:4]
                if province not in seen_provinces:
                    community_iso = SPAIN_PROVINCE_COMMUNITY.get(province)
                    if community_iso is None:
                        raise ValueError(
                            f"INE province {province} has no autonomous-community parent"
                        )
                    manifest["places"].append(
                        _place(
                            source="ine-province",
                            source_id=province,
                            version=version,
                            country="ES",
                            place_type="admin_region",
                            name=province_name,
                            parent_source_id=SPAIN_AUTONOMOUS_COMMUNITIES[
                                community_iso
                            ][0],
                            parent_source="ine-autonomous-community",
                            admin_level="province",
                        )
                    )
                    seen_provinces.add(province)
                code = f"{province}{municipality}"
                manifest["places"].append(
                    _place(
                        source=source,
                        source_id=code,
                        version=version,
                        country="ES",
                        place_type="locality",
                        name=name,
                        parent_source_id=province,
                        parent_source="ine-province",
                        admin_level="municipality",
                        metadata={"official_code": code, "check_digit": check_digit},
                    )
                )


def parse_germany(path: Path, manifest: dict[str, Any]) -> None:
    version = "DESTATIS-GV-ISYS-2026-06-30"
    source = "destatis-municipality"
    manifest["countries"].append(
        _country("DE", "Germany", "destatis-country", "DE", version)
    )
    with zipfile.ZipFile(path) as archive:
        shared = _xlsx_shared_strings(archive)
        rows = list(_xlsx_rows(archive, "xl/worksheets/sheet2.xml", shared))
        states: set[str] = set()
        districts: set[str] = set()
        state_names: dict[str, str] = {}
        district_names: dict[str, str] = {}
        for row in rows:
            if len(row) < 8:
                continue
            if row[0] == "10" and row[2]:
                state_names[row[2]] = row[7]
            elif row[0] == "40" and row[2] and row[3] and row[4]:
                district_names[f"{row[2]}{row[3]}{row[4]}"] = row[7]
        for row in rows:
            if len(row) < 8 or row[0] != "60" or row[1] == "66":
                continue
            state, rb, district, association, municipality = (row + [""] * 7)[2:7]
            name = row[7]
            if not state or not district or not municipality:
                continue
            if state not in states:
                manifest["places"].append(
                    _place(
                        source="destatis-state",
                        source_id=state,
                        version=version,
                        country="DE",
                        place_type="admin_region",
                        name=state_names.get(state, f"Land {state}"),
                        admin_level="state",
                    )
                )
                states.add(state)
            district_id = f"{state}{rb}{district}"
            if district_id not in districts:
                manifest["places"].append(
                    _place(
                        source="destatis-district",
                        source_id=district_id,
                        version=version,
                        country="DE",
                        place_type="admin_region",
                        name=district_names.get(district_id, f"District {district_id}"),
                        parent_source_id=state,
                        parent_source="destatis-state",
                        admin_level="district",
                    )
                )
                districts.add(district_id)
            ags = f"{state}{rb}{district}{municipality}"
            longitude = row[14] if len(row) > 14 else None
            latitude = row[15] if len(row) > 15 else None
            manifest["places"].append(
                _place(
                    source=source,
                    source_id=ags,
                    version=version,
                    country="DE",
                    place_type="locality",
                    name=name,
                    parent_source_id=district_id,
                    parent_source="destatis-district",
                    admin_level="municipality",
                    latitude=latitude.replace(",", ".") if latitude else None,
                    longitude=longitude.replace(",", ".") if longitude else None,
                    metadata={
                        "ags": ags,
                        "association_code": association,
                        "text_indicator": row[1],
                    },
                )
            )


def parse_algeria(
    ons_path: Path,
    joradp_path: Path,
    wilayas_path: Path,
    communes_path: Path,
    manifest: dict[str, Any],
) -> None:
    supplement_hash = hashlib.sha256(
        wilayas_path.read_bytes() + communes_path.read_bytes()
    ).hexdigest()[:12]
    version = f"ONS-CGN-2021+JORADP-26-06-2026+SUP-{supplement_hash}"
    identity_source = "algeria-wilaya"
    commune_source = "algeria-commune"
    manifest["countries"].append(
        _country("DZ", "Algeria", "algeria-country", "DZ", version)
    )
    wilayas = json.loads(wilayas_path.read_text(encoding="utf-8"))
    communes = json.loads(communes_path.read_text(encoding="utf-8"))
    if len(wilayas) != 69 or len(communes) != 1541:
        raise ValueError(
            "Algeria source must contain exactly 69 wilayas and 1541 communes"
        )

    ons_communes = _parse_ons_communes(ons_path)
    official_assignments = _parse_joradp_assignments(joradp_path)
    official_by_wilaya: dict[int, dict[str, str]] = {}
    for code, names in official_assignments.items():
        official_by_wilaya[code] = {_name_key(name): name for name in names}
        for alias, canonical in OFFICIAL_NAME_ALIASES.items():
            if canonical in names:
                official_by_wilaya[code][alias] = canonical
        source_wilaya = next(
            (row for row in wilayas if int(row["code"]) == code),
            None,
        )
        if source_wilaya is None:
            raise ValueError(f"Supplemental source is missing affected wilaya {code}")
        source_wilaya["name"] = names[0]

    ons_by_wilaya_and_name: dict[tuple[int, str], tuple[str, str]] = {}
    ons_by_name: dict[str, list[tuple[str, str]]] = {}
    for official_id, official in ons_communes.items():
        key = (int(official["wilaya_code"]), _name_key(official["name"]))
        if key in ons_by_wilaya_and_name:
            raise ValueError(f"Duplicate ONS name within wilaya: {key}")
        ons_by_wilaya_and_name[key] = (official_id, official["name"])
        ons_by_name.setdefault(key[1], []).append((official_id, official["name"]))

    for row in wilayas:
        code = f"{int(row['code']):02d}"
        manifest["places"].append(
            _place(
                source=identity_source,
                source_id=code,
                version=version,
                country="DZ",
                place_type="admin_region",
                name=row["name"],
                admin_level="wilaya",
                latitude=row.get("latitude"),
                longitude=row.get("longitude"),
                metadata={
                    "official_code": code,
                    "identity_authority": (
                        "JORADP Law 26-06" if int(code) >= 59 else "ONS CGN 2021"
                    ),
                },
            )
        )
        if row.get("name_ar"):
            manifest["alternate_names"].append(
                {
                    "place_source": identity_source,
                    "place_source_id": code,
                    "name": row["name_ar"],
                    "language": "ar",
                    "source": "algeria-coordinate-supplement-ar",
                    "source_id": f"wilaya:{code}:ar",
                    "source_version": f"algeria-supplement-{supplement_hash}",
                }
            )

    consumed_ons_ids: set[str] = set()
    for row in communes:
        wilaya_number = int(row["wilaya_code"])
        supplement_name = row["name"]
        if wilaya_number in official_by_wilaya:
            canonical_name = official_by_wilaya[wilaya_number].get(
                _name_key(row["name"])
            )
            if canonical_name is None:
                raise ValueError(
                    f"Commune {row['name']!r} is not in JORADP Law 26-06 "
                    f"wilaya {wilaya_number:02d}"
                )
            row["name"] = canonical_name

        if 49 <= wilaya_number <= 58:
            lookup_name = ONS_NAME_ALIASES.get(
                _name_key(supplement_name), supplement_name
            )
            ons_match = ons_by_wilaya_and_name.get(
                (wilaya_number, _name_key(lookup_name))
            )
            if ons_match is None:
                raise ValueError(
                    f"Supplement commune {row['name']!r} cannot be reconciled "
                    f"to ONS CGN wilaya {wilaya_number:02d}"
                )
            official_id, ons_name = ons_match
            official = ons_communes[official_id]
        else:
            ons_wilaya = NEW_WILAYA_MOTHER.get(wilaya_number, wilaya_number)
            commune_number = int(str(row["post_code"])[-3:])
            official_id = f"{ons_wilaya:02d}{commune_number:02d}"
            official = ons_communes.get(official_id)
            if official is None:
                lookup_name = ONS_NAME_ALIASES.get(
                    _name_key(supplement_name), supplement_name
                )
                matches = ons_by_name.get(_name_key(lookup_name), [])
                if len(matches) != 1:
                    raise ValueError(
                        f"Supplement commune {supplement_name!r} cannot be "
                        f"reconciled to ONS CGN code {official_id}"
                    )
                official_id, ons_name = matches[0]
                official = ons_communes[official_id]
            else:
                ons_name = official["name"]
        if official_id in consumed_ons_ids:
            raise ValueError(f"ONS CGN commune code {official_id} was mapped twice")
        consumed_ons_ids.add(official_id)

        current_wilaya_number = (
            wilaya_number
            if wilaya_number in official_assignments
            else int(official["wilaya_code"])
        )
        wilaya = f"{current_wilaya_number:02d}"

        manifest["places"].append(
            _place(
                source=commune_source,
                source_id=official_id,
                version=version,
                country="DZ",
                place_type="locality",
                name=row["name"],
                parent_source_id=wilaya,
                parent_source=identity_source,
                admin_level="commune",
                latitude=row.get("latitude"),
                longitude=row.get("longitude"),
                metadata={
                    "official_cgn_2021_code": official_id,
                    "official_cgn_2021_name": ons_name,
                    "identity_authority": "ONS Code géographique national 2021",
                    "hierarchy_authority": "JORADP Law 26-06",
                    "supplement_id": row["id"],
                    "supplement_postal_code": row.get("post_code"),
                    "daira": row.get("daira"),
                },
            )
        )
        if row.get("name_ar"):
            manifest["alternate_names"].append(
                {
                    "place_source": commune_source,
                    "place_source_id": official_id,
                    "name": row["name_ar"],
                    "language": "ar",
                    "source": "algeria-coordinate-supplement-ar",
                    "source_id": f"commune:{official_id}:ar",
                    "source_version": f"algeria-supplement-{supplement_hash}",
                }
            )

    if consumed_ons_ids != set(ons_communes):
        missing = sorted(set(ons_communes) - consumed_ons_ids)
        raise ValueError(
            f"Algeria reconciliation did not consume every ONS CGN identity: {missing[:5]}"
        )

    for wilaya_number, official_names in official_assignments.items():
        imported = {
            row["name"]
            for row in manifest["places"]
            if row["source"] == commune_source
            and row.get("parent_source_id") == f"{wilaya_number:02d}"
        }
        expected = set(official_names)
        if imported != expected:
            raise ValueError(
                f"JORADP commune assignment mismatch for wilaya {wilaya_number}"
            )


def parse_airports(path: Path, manifest: dict[str, Any]) -> None:
    version = f"OurAirports-{date.today().isoformat()}-{_sha256(path)[:12]}"
    included = {"DZ", "FR", "ES", "DE"}
    excluded = {"closed", "heliport", "seaplane_base", "balloonport", "gliderport"}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("iso_country") not in included or row.get("type") in excluded:
                continue
            airport_type = row.get("type") or ""
            scheduled = row.get("scheduled_service") == "yes"
            if airport_type not in {"large_airport", "medium_airport", "small_airport"}:
                continue
            # The source has no reliable civil/military or private/public
            # flag. Scheduled service is the conservative passenger-use gate;
            # it excludes unscheduled military and private fields regardless
            # of nominal size.
            if not scheduled:
                continue
            iso_region = row.get("iso_region") or ""
            region_code = iso_region.partition("-")[2]
            if row["iso_country"] == "DZ":
                parent_source = "algeria-wilaya"
                parent_source_id = region_code
            elif row["iso_country"] == "FR":
                parent_source = "insee-cog-region"
                parent_source_id = FRANCE_ISO_REGION_TO_INSEE.get(region_code)
            elif row["iso_country"] == "ES":
                parent_source = "ine-autonomous-community"
                community = SPAIN_AUTONOMOUS_COMMUNITIES.get(region_code)
                parent_source_id = community[0] if community else None
            else:
                parent_source = "destatis-state"
                parent_source_id = GERMANY_ISO_STATE_TO_DESTATIS.get(region_code)
            if not parent_source_id:
                raise ValueError(
                    f"Airport {row['id']} has no reviewed canonical admin "
                    f"crosswalk for {iso_region}"
                )
            ident = row["id"]
            iata = (row.get("iata_code") or "").upper()
            icao = (row.get("icao_code") or row.get("gps_code") or "").upper()
            manifest["places"].append(
                _place(
                    source="ourairports",
                    source_id=ident,
                    version=version,
                    country=row["iso_country"],
                    place_type="airport",
                    name=row["name"],
                    parent_source_id=parent_source_id,
                    parent_source=parent_source,
                    admin_level="airport",
                    latitude=row.get("latitude_deg"),
                    longitude=row.get("longitude_deg"),
                    iata_code=iata,
                    icao_code=icao,
                    airport_type=airport_type,
                    passenger_use=True,
                    legacy_city=row.get("municipality") or "",
                    metadata={
                        "scheduled_service": scheduled,
                        "iso_region": iso_region,
                        "municipality_hint": row.get("municipality") or "",
                        "mapping_policy": "explicit-maintained-mapping-required",
                    },
                )
            )


def load_airport_mappings(path: Path, manifest: dict[str, Any]) -> None:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Airport mapping file must contain a JSON list of objects")
    manifest["airport_mappings"].extend(rows)


# Source-context exceptions reviewed for commercial served-city semantics or
# municipality names that cannot be reconciled by a lossless catalogue-name
# prefix.  The key is the stable OurAirports row id; values are the stable
# catalogue source/id pair.  Keeping this table in source control makes every
# exception inspectable and repeatable rather than guessing from display text.
AIRPORT_LOCALITY_OVERRIDES: dict[str, tuple[str, str]] = {
    # Algeria (source municipality labels and accented spellings)
    "2056": ("algeria-commune", "1101"),  # Tamanrasset
    "2057": ("algeria-commune", "1805"),  # Taher
    "2058": ("algeria-commune", "4502"),  # Mechria
    "2062": ("algeria-commune", "1201"),  # Tebessa
    "2077": ("algeria-commune", "5801"),  # El Meniaa
    "2083": ("algeria-commune", "3906"),  # Guemar
    # Germany (airport municipality is not always the commercial city)
    "301881": ("destatis-municipality", "11000000"),  # Berlin
    "2210": ("destatis-municipality", "14612000"),
    "2211": ("destatis-municipality", "16051000"),
    "2214": ("destatis-municipality", "02000000"),
    "2213": ("destatis-municipality", "05566012"),
    "2216": ("destatis-municipality", "05315000"),
    "2217": ("destatis-municipality", "05111000"),
    "2219": ("destatis-municipality", "09564000"),
    "2220": ("destatis-municipality", "14730270"),
    "2221": ("destatis-municipality", "10041100"),
    "2222": ("destatis-municipality", "08111000"),
    "2224": ("destatis-municipality", "03241001"),
    "2225": ("destatis-municipality", "04011000"),
    "2227": ("destatis-municipality", "06412000"),  # HHN serves Frankfurt
    "2228": ("destatis-municipality", "08222000"),
    "2236": ("destatis-municipality", "01003000"),
    "2244": ("destatis-municipality", "05774016"),
    "2247": ("destatis-municipality", "05913000"),
    "2256": ("destatis-municipality", "08435016"),
    "2288": ("destatis-municipality", "03402000"),
    "28751": ("destatis-municipality", "03455021"),
    "28614": ("destatis-municipality", "03452013"),
    "2291": ("destatis-municipality", "03457002"),
    "2292": ("destatis-municipality", "03452020"),
    "28588": ("destatis-municipality", "03455020"),
    "2739": ("destatis-municipality", "13072062"),
    # Spain (island/airport and commercial city nomenclature)
    "3077": ("ine-municipality", "35003"),
    "3078": ("ine-municipality", "38003"),
    "3079": ("ine-municipality", "38048"),
    "3080": ("ine-municipality", "38037"),
    "3081": ("ine-municipality", "35016"),
    "3082": ("ine-municipality", "35018"),
    "3083": ("ine-municipality", "38017"),
    "3084": ("ine-municipality", "38023"),
    "3997": ("ine-municipality", "03014"),
    "3999": ("ine-municipality", "33016"),
    "300859": ("ine-municipality", "12040"),
    "4011": ("ine-municipality", "18087"),
    "4013": ("ine-municipality", "07026"),
    "4018": ("ine-municipality", "24189"),
    "4020": ("ine-municipality", "29067"),
    "4021": ("ine-municipality", "07032"),
    "308134": ("ine-municipality", "30030"),
    "4035": ("ine-municipality", "07040"),
    "4025": ("ine-municipality", "31201"),
    "4039": ("ine-municipality", "25203"),
    "4042": ("ine-municipality", "46250"),
    "4045": ("ine-municipality", "01059"),
    "4049": ("ine-municipality", "41091"),
    # France (commercial served city overrides and ambiguous names)
    "4060": ("insee-cog-commune", "33063"),
    "4064": ("insee-cog-commune", "17300"),
    "4065": ("insee-cog-commune", "86194"),
    "4067": ("insee-cog-commune", "87085"),
    "4070": ("insee-cog-commune", "31555"),
    "4071": ("insee-cog-commune", "64445"),
    "4073": ("insee-cog-commune", "65440"),
    "4082": ("insee-cog-commune", "81065"),
    "4086": ("insee-cog-commune", "12202"),
    "28820": ("insee-cog-commune", "29155"),
    "4111": ("insee-cog-commune", "43062"),
    "4137": ("insee-cog-commune", "69123"),
    "4155": ("insee-cog-commune", "13055"),
    "4156": ("insee-cog-commune", "06088"),
    "4158": ("insee-cog-commune", "66136"),
    "4161": ("insee-cog-commune", "34172"),
    "4163": ("insee-cog-commune", "84007"),
    "4169": ("insee-cog-commune", "60057"),
    "4179": ("insee-cog-commune", "37261"),
    "4206": ("insee-cog-commune", "29019"),
    "4218": ("insee-cog-commune", "35281"),
    "4221": ("insee-cog-commune", "44109"),
    "4226": ("insee-cog-commune", "68297"),
    "29001": ("insee-cog-commune", "19031"),
    "4241": ("insee-cog-commune", "83137"),
    "4242": ("insee-cog-commune", "30189"),
}


def derive_airport_mappings(manifest: dict[str, Any]) -> None:
    """Complete one deterministic primary served mapping per active airport."""

    places = manifest["places"]
    localities = [row for row in places if row["place_type"] == "locality"]
    airports = [row for row in places if row["place_type"] == "airport"]
    by_key = {(row["source"], row["source_id"]): row for row in localities}
    covered = {
        (
            row.get("airport_source", row.get("source")),
            str(row.get("airport_source_id", "")),
        )
        for row in manifest["airport_mappings"]
        if row.get("relationship_type", "served") == "served" and row.get("is_primary")
    }
    for airport in airports:
        airport_key = (airport["source"], airport["source_id"])
        if airport_key in covered:
            continue
        override = AIRPORT_LOCALITY_OVERRIDES.get(airport["source_id"])
        if override is not None:
            locality = by_key.get(override)
            if locality is None:
                raise ValueError(
                    f"Airport override points to missing locality: {airport['source_id']}"
                )
            method = "reviewed_source_context_override"
        else:
            hint = _name_key(
                str(airport.get("metadata", {}).get("municipality_hint") or "")
            )
            candidates = [
                row
                for row in localities
                if row["country_code"] == airport["country_code"]
                and (
                    _name_key(row["name"]) == hint
                    or _name_key(row["name"]).startswith(f"{hint} ")
                )
            ]
            if len(candidates) != 1:
                raise ValueError(
                    f"Airport {airport['source_id']} has no deterministic served locality; "
                    "add an explicit AIRPORT_LOCALITY_OVERRIDES entry."
                )
            locality = candidates[0]
            method = "reviewed_source_municipality_context"
        manifest["airport_mappings"].append(
            {
                "airport_source": airport["source"],
                "airport_source_id": airport["source_id"],
                "locality_source": locality["source"],
                "locality_source_id": locality["source_id"],
                "relationship_type": "served",
                "is_primary": True,
                "source": "shiptrip-airport-locality-review",
                "source_id": f"ourairports:{airport['source_id']}:served-derived",
                "source_version": YEAR,
                "metadata": {
                    "review_basis": method,
                    "municipality_hint": airport.get("metadata", {}).get(
                        "municipality_hint", ""
                    ),
                },
            }
        )


def add_reviewed_served_locality_aliases(manifest: dict[str, Any]) -> None:
    """Project explicitly reviewed mapping aliases onto canonical localities.

    This is deliberately opt-in data on a reviewed airport mapping.  Parsing an
    airport display name or blindly treating every municipality hint as a city
    alias would recreate the ambiguity the mapping catalogue exists to remove.
    """

    places = {
        (row["source"], str(row["source_id"])): row for row in manifest["places"]
    }
    existing_source_ids = {
        (row.get("source"), row.get("source_id"))
        for row in manifest["alternate_names"]
    }
    existing_aliases = {
        (
            row.get("place_source", row.get("source")),
            str(row.get("place_source_id", "")),
            str(row.get("language") or "und").casefold(),
            _name_key(str(row.get("name") or "")),
        )
        for row in manifest["alternate_names"]
    }
    for mapping in manifest["airport_mappings"]:
        aliases = mapping.get("served_locality_aliases", [])
        if not isinstance(aliases, list) or any(
            not isinstance(alias, dict) for alias in aliases
        ):
            raise ValueError("served_locality_aliases must be a list of objects")
        if aliases and mapping.get("relationship_type", "served") != "served":
            raise ValueError("Only served airport mappings may define locality aliases")
        locality_key = (
            mapping.get("locality_source", mapping.get("source")),
            str(mapping.get("locality_source_id", "")),
        )
        locality = places.get(locality_key)
        if aliases and (locality is None or locality["place_type"] != "locality"):
            raise ValueError("A served locality alias requires a valid locality mapping")
        for index, alias in enumerate(aliases):
            name = str(alias.get("name") or "").strip()
            language = str(alias.get("language") or "und").casefold().strip()
            if not name or not _name_key(name):
                raise ValueError("A served locality alias requires a searchable name")
            source = mapping.get("source", "shiptrip-airport-locality-review")
            source_id = f"{mapping.get('source_id', '')}:locality-alias:{index}"
            source_key = (source, source_id)
            if source_key in existing_source_ids:
                raise ValueError(f"Duplicate reviewed locality alias source {source_key}")
            alias_key = (*locality_key, language, _name_key(name))
            if alias_key in existing_aliases:
                raise ValueError(f"Duplicate reviewed locality alias {alias_key}")
            existing_source_ids.add(source_key)
            existing_aliases.add(alias_key)
            manifest["alternate_names"].append(
                {
                    "place_source": locality["source"],
                    "place_source_id": locality["source_id"],
                    "name": name,
                    "language": language,
                    "source": source,
                    "source_id": source_id,
                    "source_version": mapping.get("source_version", YEAR),
                    "metadata": {
                        "review_basis": str(alias.get("review_basis") or ""),
                        "airport_mapping_source_id": mapping.get("source_id", ""),
                    },
                }
            )


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Fail closed on the launch-country and identity invariants."""

    places = manifest["places"]
    keys = [(row["source"], row["source_id"]) for row in places]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate place source identity in generated manifest")
    by_country_type: dict[tuple[str, str], int] = {}
    for row in places:
        key = (row["country_code"], row["place_type"])
        by_country_type[key] = by_country_type.get(key, 0) + 1
    if by_country_type.get(("DZ", "admin_region")) != 69:
        raise ValueError("Algeria must contain all 69 current wilayas")
    if by_country_type.get(("DZ", "locality")) != 1541:
        raise ValueError("Algeria must contain all 1541 current communes")
    wilaya_codes = {
        row["source_id"] for row in places if row["source"] == "algeria-wilaya"
    }
    if not {f"{code:02d}" for code in range(59, 70)}.issubset(wilaya_codes):
        raise ValueError("The eleven 2026 Algerian wilayas (59-69) are missing")
    place_keys = set(keys)
    place_by_key = {(row["source"], row["source_id"]): row for row in places}
    for row in places:
        parent_id = row.get("parent_source_id")
        if parent_id is not None:
            parent_key = (row.get("parent_source", row["source"]), str(parent_id))
            if parent_key not in place_keys:
                raise ValueError(
                    f"Missing parent for {row['source']}:{row['source_id']}"
                )
            if place_by_key[parent_key]["country_code"] != row["country_code"]:
                raise ValueError(
                    f"Cross-country parent for {row['source']}:{row['source_id']}"
                )
        if row["country_code"] == "DZ" and row["place_type"] == "locality":
            if row.get("parent_source") != "algeria-wilaya":
                raise ValueError(
                    f"Algerian commune has an invalid wilaya parent source: {row['source_id']}"
                )
    if by_country_type.get(("FR", "locality")) != 34875:
        raise ValueError("INSEE COG 2026 commune coverage changed unexpectedly")
    if by_country_type.get(("FR", "admin_region")) != 119:
        raise ValueError("INSEE COG 2026 parent coverage changed unexpectedly")
    if by_country_type.get(("ES", "locality")) != 8132:
        raise ValueError("INE 2026 municipality coverage changed unexpectedly")
    if by_country_type.get(("ES", "admin_region")) != 71:
        raise ValueError("INE 2026 autonomous/province coverage changed unexpectedly")
    if by_country_type.get(("DE", "locality")) != 10749:
        raise ValueError("Destatis 2026 municipality coverage changed unexpectedly")
    if by_country_type.get(("DE", "admin_region")) != 417:
        raise ValueError("Destatis 2026 parent coverage changed unexpectedly")
    airports = [row for row in places if row["place_type"] == "airport"]
    if not airports:
        raise ValueError("No airports were generated")
    airport_counts = {
        code: sum(1 for row in airports if row["country_code"] == code)
        for code in EXPECTED_SELECTABLE_AIRPORTS
    }
    if airport_counts != EXPECTED_SELECTABLE_AIRPORTS:
        raise ValueError(
            "Scheduled-service airport coverage changed unexpectedly: "
            f"{airport_counts!r}"
        )
    for row in airports:
        if row.get("latitude") in (None, "") or row.get("longitude") in (None, ""):
            raise ValueError(f"Airport lacks coordinates: {row['source_id']}")
        if row["country_code"] not in {"DZ", "FR", "ES", "DE"}:
            raise ValueError(
                f"Airport has an unsupported country: {row['country_code']}"
            )
        if row.get("airport_type") not in {
            "large_airport",
            "medium_airport",
            "small_airport",
        }:
            raise ValueError(
                f"Airport filtering leaked an unsupported type: {row['source_id']}"
            )
        if row.get("passenger_use") is not True:
            raise ValueError(f"Airport is not marked passenger-use: {row['source_id']}")
        if row.get("metadata", {}).get("scheduled_service") is not True:
            raise ValueError(f"Airport is not scheduled-service: {row['source_id']}")
        parent_key = (row.get("parent_source"), str(row.get("parent_source_id", "")))
        parent = place_by_key.get(parent_key)
        if parent is None or parent["place_type"] != "admin_region":
            raise ValueError(
                f"Airport lacks canonical admin context: {row['source_id']}"
            )
    alternate_keys = [
        (row.get("source"), row.get("source_id")) for row in manifest["alternate_names"]
    ]
    if len(alternate_keys) != len(set(alternate_keys)):
        raise ValueError("Duplicate alternate-name source identity")
    for row in manifest["alternate_names"]:
        place_key = (
            row.get("place_source", row.get("source")),
            str(row.get("place_source_id", "")),
        )
        if place_key not in place_keys:
            raise ValueError(f"Alternate name references unknown place {place_key}")
    mapping_keys = [
        (row.get("source"), row.get("source_id"))
        for row in manifest["airport_mappings"]
    ]
    if len(mapping_keys) != len(set(mapping_keys)):
        raise ValueError("Duplicate airport mapping source identity")
    airport_keys = {(row["source"], row["source_id"]) for row in airports}
    for row in manifest["airport_mappings"]:
        airport_key = (
            row.get("airport_source", row.get("source")),
            str(row.get("airport_source_id", "")),
        )
        if airport_key not in airport_keys:
            raise ValueError(
                f"Airport mapping references unknown airport {airport_key}"
            )
        locality_key = (
            row.get("locality_source", row.get("source")),
            str(row.get("locality_source_id", "")),
        )
        locality = place_by_key.get(locality_key)
        if locality is None or locality["place_type"] != "locality":
            raise ValueError(
                f"Airport mapping references invalid locality {locality_key}"
            )
        if locality["country_code"] != place_by_key[airport_key]["country_code"]:
            raise ValueError(f"Airport mapping crosses countries: {airport_key}")
        if row.get("relationship_type", "served") not in {"served", "physical"}:
            raise ValueError(
                f"Airport mapping has invalid relationship type: "
                f"{row.get('relationship_type')!r}"
            )
    served_primary_counts: dict[tuple[str, str], int] = {}
    for row in manifest["airport_mappings"]:
        if (
            row.get("relationship_type", "served") == "served"
            and row.get("is_primary")
            and row.get("active", True)
        ):
            key = (
                row.get("airport_source", row.get("source")),
                str(row.get("airport_source_id", "")),
            )
            served_primary_counts[key] = served_primary_counts.get(key, 0) + 1
    duplicate_primary = {
        key: count for key, count in served_primary_counts.items() if count != 1
    }
    if duplicate_primary:
        raise ValueError(
            "Every active/selectable airport requires exactly one primary "
            f"served locality; invalid {duplicate_primary!r}."
        )
    served_primary = set(served_primary_counts)
    missing_served = airport_keys - served_primary
    if missing_served:
        raise ValueError(
            "Every active/selectable airport requires one primary served locality; "
            f"missing {len(missing_served)} mappings."
        )


def build(args: argparse.Namespace) -> dict[str, Any]:
    source_dir = Path(args.source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    if args.download:
        for key, url in DOWNLOADS.items():
            target = source_dir / Path(urlparse(url).path).name
            if key == "algeria_official":
                target = source_dir / "F2026025.pdf"
            elif key == "algeria_ons":
                target = source_dir / "ons-code-2021.pdf"
            elif key == "algeria_wilayas":
                target = source_dir / "wilayas.json"
            elif key == "algeria_communes":
                target = source_dir / "communes.json"
            elif key == "france":
                target = source_dir / "france.zip"
            elif key == "germany":
                target = source_dir / "germany.xlsx"
            elif key == "airports":
                target = source_dir / "airports.csv"
            _download(url, target)
        france_dir = source_dir / "france"
        france_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(source_dir / "france.zip") as archive:
            _extract_zip(archive, france_dir)
    manifest: dict[str, Any] = {
        "format_version": 1,
        "generated_at": date.today().isoformat(),
        "countries": [],
        "places": [],
        "alternate_names": [],
        "airport_mappings": [],
        "sources": [
            {
                "name": "JORADP Law 26-06",
                "url": DOWNLOADS["algeria_official"],
                "role": "Algeria current hierarchy authority",
                "sha256": _sha256(source_dir / "F2026025.pdf"),
            },
            {
                "name": "ONS CGN 2021",
                "url": DOWNLOADS["algeria_ons"],
                "role": "Algeria official baseline commune codes",
                "sha256": _sha256(source_dir / "ons-code-2021.pdf"),
            },
            {
                "name": "Algeria wilaya coordinate/name supplement",
                "url": DOWNLOADS["algeria_wilayas"],
                "role": "coordinates and Arabic names",
                "sha256": _sha256(source_dir / "wilayas.json"),
            },
            {
                "name": "Algeria commune coordinate/name supplement",
                "url": DOWNLOADS["algeria_communes"],
                "role": "coordinates, Arabic names and reconciliation hints",
                "sha256": _sha256(source_dir / "communes.json"),
            },
            {
                "name": "INSEE COG 2026",
                "url": DOWNLOADS["france"],
                "role": "France official codes",
                "sha256": _sha256(source_dir / "france.zip"),
            },
            {
                "name": "INE municipal register 2026",
                "url": DOWNLOADS["spain"],
                "role": "Spain official codes",
                "sha256": _sha256(source_dir / "26codmun.xlsx"),
            },
            {
                "name": "Destatis GV-ISys",
                "url": DOWNLOADS["germany"],
                "role": "Germany official AGS",
                "sha256": _sha256(source_dir / "germany.xlsx"),
            },
            {
                "name": "OurAirports",
                "url": DOWNLOADS["airports"],
                "role": "airport supplement",
                "sha256": _sha256(source_dir / "airports.csv"),
            },
        ],
    }
    parse_algeria(
        source_dir / "ons-code-2021.pdf",
        source_dir / "F2026025.pdf",
        source_dir / "wilayas.json",
        source_dir / "communes.json",
        manifest,
    )
    parse_france(source_dir / "france.zip", manifest)
    parse_spain(source_dir / "26codmun.xlsx", manifest)
    parse_germany(source_dir / "germany.xlsx", manifest)
    parse_airports(source_dir / "airports.csv", manifest)
    if args.airport_mappings:
        mapping_path = Path(args.airport_mappings)
        load_airport_mappings(mapping_path, manifest)
        manifest["sources"].append(
            {
                "name": "ShipTrip reviewed airport/locality mappings",
                "file": mapping_path.name,
                "role": "explicit served and physical locality relationships",
                "sha256": _sha256(mapping_path),
            }
        )
    derive_airport_mappings(manifest)
    add_reviewed_served_locality_aliases(manifest)
    validate_manifest(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=".geography-sources")
    parser.add_argument("--output", default="geography-manifest-2026.json")
    parser.add_argument(
        "--airport-mappings",
        default=str(Path(__file__).with_name("airport_locality_mappings_2026.json")),
        help="Optional reviewed JSON list of explicit airport/locality mapping rows",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the fixed allow-listed sources first",
    )
    args = parser.parse_args()
    manifest = build(args)
    output = Path(args.output)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    counts = {
        "countries": len(manifest["countries"]),
        "places": len(manifest["places"]),
        "alternate_names": len(manifest["alternate_names"]),
        "airport_mappings": len(manifest["airport_mappings"]),
    }
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()

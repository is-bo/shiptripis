#!/usr/bin/env bash
# PREPARATION ONLY in V1. Run on a real server only during authorized V3.
set -euo pipefail
mode=${1:---help}
if [[ "$mode" == --help ]]; then
  echo 'V3 only: bootstrap.sh setup DEPLOY_USER PUBLIC_KEY_FILE SSH_SOURCE_CIDR PUBLIC_INTERFACE'
  echo 'After a successful separate key login: bootstrap.sh harden-ssh --key-access-confirmed'
  exit 0
fi
[[ $EUID -eq 0 ]] || { echo 'Run as root during V3' >&2; exit 1; }
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Requires Ubuntu 24.04' >&2; exit 1; }
[[ $(dpkg --print-architecture) == amd64 ]] || { echo 'Requires x86-64 / amd64' >&2; exit 1; }
if [[ "$mode" == harden-ssh ]]; then
  [[ ${2:-} == --key-access-confirmed ]] || { echo 'First prove a separate SSH key login, then explicitly confirm it' >&2; exit 1; }
  cat > /etc/ssh/sshd_config.d/00-wacla-hardening.conf <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
X11Forwarding no
AllowTcpForwarding local
EOF
  /usr/sbin/sshd -t
  systemctl reload ssh
  exit 0
fi
[[ "$mode" == setup && $# -eq 5 ]] || exit 1
deploy_user=$2
key_file=$3
ssh_source=$4
public_interface=$5
[[ "$deploy_user" =~ ^[a-z][a-z0-9_-]{0,31}$ && "$deploy_user" != root ]] || exit 1
[[ -f "$key_file" && "$public_interface" =~ ^[a-zA-Z0-9_.:-]+$ ]] || exit 1
python3 -c 'import ipaddress,sys; assert ipaddress.ip_network(sys.argv[1]).prefixlen>0' "$ssh_source"
if grep -q 'PRIVATE KEY' "$key_file"; then
  echo 'Supply only a public SSH key file; private keys must stay on the operator device' >&2
  exit 1
fi
ssh-keygen -l -f "$key_file" >/dev/null
ip link show "$public_interface" >/dev/null
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg ufw fail2ban unattended-upgrades python3 sudo
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable\n' > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
if ! getent passwd "$deploy_user" >/dev/null; then useradd -m -s /bin/bash "$deploy_user"; fi
usermod -aG docker,sudo "$deploy_user"
if ! getent group 10001 >/dev/null; then groupadd -g 10001 wacla-runtime; fi
runtime_group=$(getent group 10001 | cut -d: -f1)
[[ "$runtime_group" == wacla-runtime ]] || { echo 'GID 10001 is already assigned; resolve before granting secrets access' >&2; exit 1; }
usermod -aG "$runtime_group" "$deploy_user"
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$deploy_user" > /etc/sudoers.d/wacla-deploy
chmod 0440 /etc/sudoers.d/wacla-deploy
visudo -cf /etc/sudoers.d/wacla-deploy
deploy_home=$(getent passwd "$deploy_user" | cut -d: -f6)
install -d -o "$deploy_user" -g "$deploy_user" -m 0700 "$deploy_home/.ssh"
touch "$deploy_home/.ssh/authorized_keys"
while IFS= read -r public_key || [[ -n "$public_key" ]]; do
  [[ -z "$public_key" ]] || grep -qxF "$public_key" "$deploy_home/.ssh/authorized_keys" || printf '%s\n' "$public_key" >> "$deploy_home/.ssh/authorized_keys"
done < "$key_file"
chown "$deploy_user:$deploy_user" "$deploy_home/.ssh/authorized_keys"
chmod 0600 "$deploy_home/.ssh/authorized_keys"
install -d -o "$deploy_user" -g "$runtime_group" -m 0750 /etc/wacla /etc/wacla/secrets
install -d -o "$deploy_user" -g "$deploy_user" -m 0700 /var/lib/wacla
install -d -o "$deploy_user" -g "$deploy_user" -m 0750 /opt/wacla
# Host CLI, timers and boot recovery share one state-file owner. Docker/runtime
# supplementary groups are loaded by systemd for this deployment identity.
for unit in stack backup scheduled monitor; do
  identity_dir="/etc/systemd/system/wacla-${unit}.service.d"
  install -d -m 0755 "$identity_dir"
  printf '[Service]\nUser=%s\nGroup=%s\n' "$deploy_user" "$deploy_user" > "$identity_dir/10-deployment-user.conf"
done
# Merge logging defaults; preserve any existing Docker daemon configuration.
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/etc/docker/daemon.json')
d=json.loads(p.read_text()) if p.exists() else {}
d.setdefault('log-driver','json-file')
if d['log-driver']=='json-file':
 opts=d.setdefault('log-opts',{})
 opts.setdefault('max-size','10m')
 opts.setdefault('max-file','5')
p.write_text(json.dumps(d,indent=2)+'\n')
PY
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
cat > /etc/fail2ban/jail.d/wacla.local <<'EOF'
[sshd]
enabled = true
backend = systemd
EOF
cat > /etc/sysctl.d/60-wacla-redis.conf <<'EOF'
# Redis background persistence uses fork; memory remains bounded by cgroups.
vm.overcommit_memory = 1
EOF
sysctl -p /etc/sysctl.d/60-wacla-redis.conf
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$ssh_source" to any port 22 proto tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
printf '%s\n' "$public_interface" > /etc/wacla/public-interface
install -m 0755 "$(dirname "$0")/docker-firewall.sh" /usr/local/sbin/wacla-docker-firewall
install -m 0644 "$(dirname "$0")/systemd/wacla-docker-firewall.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now docker fail2ban unattended-upgrades wacla-docker-firewall.service
echo 'Setup complete. Docker group grants root-equivalent access. Review all existing firewall/SSH rules.'
echo 'Keep this session open. Prove a separate deploy-user key login and sudo before harden-ssh.'
echo 'No password/root SSH authentication was disabled by setup. No stack/timers were activated.'

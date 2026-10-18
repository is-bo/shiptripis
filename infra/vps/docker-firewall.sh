#!/bin/sh
# UFW alone does not filter Docker's published ports after DNAT.
set -eu
public_interface=$(cat /etc/wacla/public-interface)
iptables -N WACLA-INGRESS 2>/dev/null || true
iptables -F WACLA-INGRESS
iptables -A WACLA-INGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A WACLA-INGRESS -p tcp -m multiport --dports 80,443 -j RETURN
iptables -A WACLA-INGRESS -j DROP
iptables -C DOCKER-USER -i "$public_interface" -j WACLA-INGRESS 2>/dev/null || \
  iptables -I DOCKER-USER 1 -i "$public_interface" -j WACLA-INGRESS

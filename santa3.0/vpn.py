import os
import json
import urllib.parse
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def parse_vless(url: str) -> dict:
    u = urllib.parse.urlparse(url)
    if u.scheme != "vless":
        raise ValueError("invalid scheme")
    user = u.username
    host = u.hostname
    port = u.port or 443
    q = urllib.parse.parse_qs(u.query)
    def get(k: str, default: Optional[str] = None) -> Optional[str]:
        v = q.get(k, [])
        return v[0] if v else default
    typ = get("type", "tcp")
    sec = get("security", "reality")
    pbk = get("pbk", "")
    fp = get("fp", "chrome")
    sni = get("sni", host or "")
    sid = get("sid", "")
    spx = urllib.parse.unquote(get("spx", "/"))
    tag = urllib.parse.unquote(u.fragment or "")
    return {
        "uuid": user,
        "host": host,
        "port": port,
        "type": typ,
        "security": sec,
        "pbk": pbk,
        "fp": fp,
        "sni": sni,
        "sid": sid,
        "spx": spx,
        "tag": tag,
    }


def build_xray_config(v: dict, socks_port: int) -> dict:
    return {
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": True},
                "tag": "socks-in",
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": v["host"],
                            "port": v["port"],
                            "users": [
                                {
                                    "id": v["uuid"],
                                    "encryption": "none",
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": {
                    "network": v["type"],
                    "security": v["security"],
                    "realitySettings": {
                        "serverName": v["sni"],
                        "publicKey": v["pbk"],
                        "shortId": v["sid"],
                        "spiderX": v["spx"],
                        "fingerprint": v["fp"],
                    },
                },
                "tag": "vless-out",
            }
        ],
    }


def write_temp_config(cfg: dict) -> Path:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        p = Path(f.name)
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


def start_vpn(url: str, xray_path: str, socks_port: int = 1080) -> Tuple[subprocess.Popen, Path]:
    v = parse_vless(url)
    cfg = build_xray_config(v, socks_port)
    cfg_path = write_temp_config(cfg)
    proc = subprocess.Popen([xray_path, "-c", str(cfg_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, cfg_path

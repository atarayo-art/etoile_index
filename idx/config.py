"""利用者設定（``~/etoile-index-data/config.yaml``）。

例::

    timezone: Asia/Tokyo
    org_rules:                 # プロジェクト名・タイトルに含まれる語から法人を決める
      - org: EXAMPLE-A
        match: [青空商店, 例示プロジェクト]
      - org: 個人
        match: [家計, 旅行]
    default_org: ""
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


@dataclass
class OrgRule:
    org: str
    match: list[str] = field(default_factory=list)

    def matches(self, *texts: str) -> bool:
        for pat in self.match:
            for t in texts:
                if not t:
                    continue
                if pat.lower() in t.lower():
                    return True
                try:
                    if re.search(pat, t):
                        return True
                except re.error:
                    pass
        return False


@dataclass
class Config:
    timezone: str = "Asia/Tokyo"
    org_rules: list[OrgRule] = field(default_factory=list)
    default_org: str = ""
    # 会話UUID → プロジェクト名。エクスポートに紐付けが無い場合の手動補完用
    project_overrides: dict[str, str] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo("UTC")

    def resolve_org(self, *texts: str) -> str:
        for rule in self.org_rules:
            if rule.matches(*texts):
                return rule.org
        return self.default_org


def load_config(path: Path | None) -> Config:
    if not path or not Path(path).exists():
        return Config()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = [
        OrgRule(org=str(r.get("org", "")), match=[str(m) for m in (r.get("match") or [])])
        for r in (raw.get("org_rules") or [])
        if isinstance(r, dict)
    ]
    return Config(
        timezone=str(raw.get("timezone") or "Asia/Tokyo"),
        org_rules=rules,
        default_org=str(raw.get("default_org") or ""),
        project_overrides={str(k): str(v) for k, v in (raw.get("project_overrides") or {}).items()},
    )

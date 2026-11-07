"""Настройки в config.ini рядом с программой."""
from __future__ import annotations

import configparser
from dataclasses import dataclass, field

from .paths import app_dir

CONFIG_PATH = app_dir() / "config.ini"


@dataclass
class DbConfig:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "stroyagg"
    user: str = "postgres"
    password: str = ""
    sslmode: str = "prefer"


@dataclass
class SearchConfig:
    max_per_site: int = 15
    headless: bool = False
    deep_delivery: bool = False
    timeout_s: int = 40
    enabled_sites: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    db: DbConfig = field(default_factory=DbConfig)
    search: SearchConfig = field(default_factory=SearchConfig)

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        cp = configparser.ConfigParser()
        if CONFIG_PATH.exists():
            cp.read(CONFIG_PATH, encoding="utf-8")
        if cp.has_section("database"):
            d = cp["database"]
            cfg.db = DbConfig(
                host=d.get("host", "localhost"), port=d.getint("port", 5432),
                dbname=d.get("dbname", "stroyagg"), user=d.get("user", "postgres"),
                password=d.get("password", ""), sslmode=d.get("sslmode", "prefer"),
            )
        if cp.has_section("search"):
            s = cp["search"]
            cfg.search = SearchConfig(
                max_per_site=s.getint("max_per_site", 15), headless=s.getboolean("headless", False),
                deep_delivery=s.getboolean("deep_delivery", False), timeout_s=s.getint("timeout_s", 40),
                enabled_sites=[x for x in s.get("enabled_sites", "").split(",") if x],
            )
        return cfg

    def save(self):
        cp = configparser.ConfigParser()
        cp["database"] = {k: str(v) for k, v in self.db.__dict__.items()}
        s = dict(self.search.__dict__)
        s["enabled_sites"] = ",".join(self.search.enabled_sites)
        cp["search"] = {k: str(v) for k, v in s.items()}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cp.write(f)

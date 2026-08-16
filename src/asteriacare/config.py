"""Environment-driven configuration. No secrets live in code."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str

    salesforce_client_id: str
    salesforce_client_secret: str
    salesforce_token_url: str
    salesforce_api_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        def require(name: str, default: str = "") -> str:
            return os.environ.get(name, default)

        return cls(
            anthropic_api_key=require("ANTHROPIC_API_KEY"),
            anthropic_model=require("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            salesforce_client_id=require("SALESFORCE_CLIENT_ID"),
            salesforce_client_secret=require("SALESFORCE_CLIENT_SECRET"),
            salesforce_token_url=require("SALESFORCE_TOKEN_URL"),
            salesforce_api_url=require("SALESFORCE_API_URL"),
        )

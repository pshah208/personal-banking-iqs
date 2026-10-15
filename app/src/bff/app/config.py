"""Configuration for the Mortgage Renewal Concierge BFF."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass
class Settings:
    # --- Entra / auth ---
    tenant_id: str = os.getenv("AAD_TENANT_ID", "")
    client_id: str = os.getenv("AAD_CLIENT_ID", "")
    client_secret: str = os.getenv("AAD_CLIENT_SECRET", "")
    api_scope: str = os.getenv("AAD_API_SCOPE", "")

    # Downstream scope the OBO exchange targets. Foundry data plane.
    foundry_scope: str = os.getenv(
        "FOUNDRY_SCOPE", "https://ai.azure.com/.default"
    )

    # --- Foundry ---
    project_endpoint: str = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
    scenario_agent_name: str = os.getenv("SCENARIO_AGENT_NAME", "pb-scenario-analyst")
    compliance_agent_name: str = os.getenv("COMPLIANCE_AGENT_NAME", "pb-compliance-reviewer")
    mission_agent_name: str = os.getenv("MISSION_AGENT_NAME", "pb-mission-agent")
    agent_name: str = os.getenv("FOUNDRY_AGENT_NAME", "mortgage-renewal-concierge")
    agent_id: str = os.getenv("FOUNDRY_AGENT_ID", "")

    # --- behaviour ---
    # When true the BFF calls Foundry with its own managed identity instead of the
    # user's token. Useful for a quick smoke test, but Work IQ will return nothing
    # because the managed identity is in no mailbox - never use it for a demo.
    allow_app_identity_fallback: bool = (
        os.getenv("ALLOW_APP_IDENTITY_FALLBACK", "false").lower() == "true"
    )
    mock_mode: bool = os.getenv("MOCK_MODE", "false").lower() == "true"
    # Display name of the deployed bank; the SPA relabels authored copy itself.
    bank_name: str = os.getenv("BANK_NAME", "CFC Bank")

    cors_origins: list[str] = field(
        default_factory=lambda: _split(
            os.getenv("CORS_ORIGINS", "http://localhost:5173")
        )
    )

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def issuers(self) -> tuple[str, ...]:
        return (
            f"https://login.microsoftonline.com/{self.tenant_id}/v2.0",
            f"https://sts.windows.net/{self.tenant_id}/",
        )

    @property
    def jwks_uri(self) -> str:
        return f"{self.authority}/discovery/v2.0/keys"

    @property
    def audiences(self) -> tuple[str, ...]:
        # v2 tokens carry the bare client id; v1 tokens carry api://<client-id>.
        return (self.client_id, f"api://{self.client_id}")

    def configured(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)


settings = Settings()

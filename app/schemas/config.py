from __future__ import annotations

from pydantic import BaseModel


class CustomerConfigIn(BaseModel):
    entity_name: str = ""
    member_state: str = ""
    default_timezone: str = "Europe/Brussels"
    dora_authority_name: str = ""
    dora_authority_contact: str = ""
    nis2_csirt_or_authority_name: str = ""
    nis2_csirt_or_authority_contact: str = ""
    gdpr_supervisory_authority_name: str = ""
    gdpr_supervisory_authority_contact: str = ""
    allow_non_eu_llm: bool = False

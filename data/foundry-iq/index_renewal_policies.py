"""Create the Azure AI Search index for renewal pricing / retention policies and
upload the corpus. This index is the Foundry IQ knowledge source for the
Mortgage Renewal Concierge agent.

Usage (one-time):
    pip install azure-search-documents==11.5.2 azure-identity

    $env:SEARCH_ENDPOINT="https://<service>.search.windows.net"
    # either a key...
    $env:SEARCH_ADMIN_KEY="<admin-key>"
    # ...or RBAC (Search Service Contributor + Search Index Data Contributor)
    #   az search service update -g <rg> -n <svc> --auth-options aadOrApiKey
    python index_renewal_policies.py

Keyword + semantic ranking only - no embedding model required. Add a vector
profile later if you want hybrid retrieval.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "brand"))
from bank_profile import rebrand  # noqa: E402  - names the deployed bank

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchableField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
)

INDEX_NAME = os.getenv("SEARCH_INDEX", "renewal-policies")
ENDPOINT = os.environ["SEARCH_ENDPOINT"]
KEY = os.getenv("SEARCH_ADMIN_KEY")

if KEY:
    from azure.core.credentials import AzureKeyCredential

    CRED = AzureKeyCredential(KEY)
else:
    from azure.identity import DefaultAzureCredential

    CRED = DefaultAzureCredential()


def build_index() -> None:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(
            name="category", type=SearchFieldDataType.String,
            filterable=True, facetable=True,
        ),
        SimpleField(
            name="effective_date", type=SearchFieldDataType.String,
            filterable=True, sortable=True,
        ),
        SearchableField(name="owner", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
    ]
    semantic = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    keywords_fields=[SemanticField(field_name="category")],
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ]
    )
    SearchIndexClient(ENDPOINT, CRED).create_or_update_index(
        SearchIndex(name=INDEX_NAME, fields=fields, semantic_search=semantic)
    )
    print(f"Index '{INDEX_NAME}' created/updated.")


def upload_docs() -> None:
    path = pathlib.Path(__file__).with_name("renewal_policies.json")
    docs = rebrand(json.loads(path.read_text(encoding="utf-8")))
    result = SearchClient(ENDPOINT, INDEX_NAME, CRED).upload_documents(documents=docs)
    ok = sum(1 for r in result if r.succeeded)
    print(f"Uploaded {ok}/{len(docs)} policy documents.")
    by_cat: dict[str, int] = {}
    for d in docs:
        by_cat[d["category"]] = by_cat.get(d["category"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<24} {n}")


if __name__ == "__main__":
    build_index()
    upload_docs()

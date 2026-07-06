"""现场一键注册 Agent Builder 资产：ES|QL 属性工具 + 矿物学家 agent。

前置: export KIBANA_URL=https://xxx.kb.region.cloud.es.io  ES_API_KEY=xxx
用法: python agent-builder/setup_agent_builder.py
Workflow 工具(RRF 检索)先在 Kibana Workflows UI 导入 workflow_rrf_search.yaml，
再到 Agent Builder Tools 里把该 workflow 注册为工具，加入下方 agent 的 tool_ids。
API 参考: CSDN 152114746 / 155241617。
"""
import json
import os
import sys
import urllib.request

KIBANA_URL = os.environ.get("KIBANA_URL", "").rstrip("/")
ES_API_KEY = os.environ.get("ES_API_KEY", "")

LOOKUP_TOOL = {
    "id": "lookup_mineral_properties",
    "type": "esql",
    "description": (
        "Look up the physical properties (Mohs hardness, streak, luster, color, "
        "crystal system, density, chemical formula) and description of a mineral "
        "species by name. Use when the user asks about a specific mineral or when "
        "you need to verify a candidate identification."
    ),
    "tags": ["minerals"],
    "configuration": {
        "query": (
            "FROM minerals-species METADATA _id "
            "| WHERE species == ?species_name "
            "| KEEP species, formula, crystal_system, hardness_min, hardness_max, "
            "streak, color, luster, density, props_text, description "
            "| LIMIT 1"
        ),
        "params": {
            "species_name": {
                "type": "keyword",
                "description": "Lowercase mineral species name, e.g. 'malachite'",
            }
        },
    },
}

FILTER_TOOL = {
    "id": "filter_minerals_by_properties",
    "type": "esql",
    "description": (
        "Find candidate mineral species by structured physical properties: "
        "Mohs hardness value and/or crystal system and/or streak. Use when the user "
        "describes field observations. Returns up to 15 candidates."
    ),
    "tags": ["minerals"],
    "configuration": {
        "query": (
            "FROM minerals-species "
            "| WHERE hardness_min <= ?hardness AND hardness_max >= ?hardness "
            "| KEEP species, formula, crystal_system, hardness_min, hardness_max, "
            "streak, color, luster "
            "| LIMIT 15"
        ),
        "params": {
            "hardness": {
                "type": "double",
                "description": "Observed Mohs hardness, e.g. 3.5",
            }
        },
    },
}

AGENT = {
    "id": "mineralogist",
    "name": "Mineralogist",
    "description": "Identifies mineral species from field observations and photos.",
    "configuration": {
        "instructions": (
            "You are an expert mineralogist. Identify mineral species from the "
            "user's observed properties (color, streak, luster, hardness, crystal "
            "system, habit) or photo descriptions.\n"
            "Workflow: 1) If the query is in Chinese, translate the mineralogical "
            "terms to English before calling tools. 2) Use "
            "mineral_hybrid_search (fusion retrieval over images+text) to get "
            "candidates. 3) Cross-check top candidates with "
            "lookup_mineral_properties and filter_minerals_by_properties. "
            "4) Answer with the single most likely species name, then list the "
            "evidence (matching properties) and 2-3 alternatives with what extra "
            "observation would discriminate them. Cite retrieved documents."
        ),
        "tools": [
            {"tool_ids": ["lookup_mineral_properties",
                          "filter_minerals_by_properties"]}
        ],
    },
}


def post(path: str, payload: dict) -> None:
    req = urllib.request.Request(
        f"{KIBANA_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "kbn-xsrf": "true",
                 "Authorization": f"ApiKey {ES_API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"  ok {path} -> {r.status}")
    except urllib.error.HTTPError as e:
        print(f"  FAIL {path}: {e.status} {e.read().decode()[:300]}")


if __name__ == "__main__":
    if not KIBANA_URL or not ES_API_KEY:
        sys.exit("先设置 KIBANA_URL 与 ES_API_KEY")
    for tool in (LOOKUP_TOOL, FILTER_TOOL):
        post("/api/agent_builder/tools", tool)
    post("/api/agent_builder/agents", AGENT)
    print("完成。到 Kibana Agent Builder 里把 workflow 工具挂到 mineralogist 上。")

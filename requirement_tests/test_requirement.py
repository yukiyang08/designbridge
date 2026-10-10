"""
test_requirement.py
測試 Requirement Analyzer（RA）在目前 routing_decision / structured_requirement
schema 下的行為，並支援「同一組測試指令 x 多個 LLM backend」的消融比較。

用法：
    python -m requirement_tests.test_requirement --batch
        跑內建測試案例，backend 固定為目前系統實際使用的 Gemini（完全重用
        production 的 _call_llm_requirement_analyzer，不是另外模擬的邏輯）。

    python -m requirement_tests.test_requirement --prompt "我想把客廳改成北歐風"
        單一指令快速測試。

    python -m requirement_tests.test_requirement --compare [--repeats 3]
        消融比較模式：同一組測試指令，分別打 Gemini（production 路徑）與
        ITRI vLLM 端點上的模型（例如 gpt-oss-120b），統計路由準確率、
        JSON 解析成功率、平均延遲，印出比較表並存成 JSON。

        ITRI 端點目前只能連到白名單 IP（見申請流程），本機要先開通道：
            ssh -L 46351:210.61.209.139:46351 <你的帳號>@<jump-host>
        再執行本腳本，或用 --vllm-base-url / 環境變數指定其他位址。
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 確保可以 import designbridge ──────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from designbridge.core.config import Config
from designbridge.core.nodes.requirement import _call_llm_requirement_analyzer
from designbridge.core.prompts.requirement_analyzer import REQUIREMENT_ANALYZER_PROMPT

OUTPUT_DIR = Path(__file__).parent / "outputs"

DEFAULT_VLLM_BASE_URL = "http://localhost:46351/v1/"
DEFAULT_VLLM_MODEL = "openai/gpt-oss-120b"

_VALID_ROUTING_DECISIONS = {"design_adjuster", "design"}

# ── 內建測試案例：每條都標了 expected_routing，用來算路由準確率 ─────────────────
# 特別放了幾條 RA prompt 裡明講的邊界規則（「只要是新增一件不存在的家具，一律
# design，不管範圍看起來多小」），這種案例最能測出模型是不是真的懂語意，
# 不是隨便關鍵字比對。
BATCH_CASES: list[dict[str, str]] = [
    {"name": "北歐風客廳", "prompt": "我想把客廳改成北歐風，喜歡白色和木質感，希望光線充足", "expected_routing": "design"},
    {"name": "工業風書房", "prompt": "書房想要工業風，需要一張大書桌和收納架，常在家工作", "expected_routing": "design"},
    {"name": "家有寵物的臥室", "prompt": "臥室想改造，家裡有一隻狗，需要耐用好清理的材質，簡約風格", "expected_routing": "design"},
    {"name": "收納不足的廚房", "prompt": "廚房收納空間嚴重不足，想增加置物架和收納櫃", "expected_routing": "design"},
    {"name": "日式禪風浴室", "prompt": "浴室想改成日式禪風，使用自然石材，整體放鬆感", "expected_routing": "design"},
    {"name": "換沙發顏色", "prompt": "只想把沙發換成深藍色", "expected_routing": "design_adjuster"},
    {"name": "換椅子顏色", "prompt": "把那把椅子換成白色的", "expected_routing": "design_adjuster"},
    {"name": "拿掉窗簾", "prompt": "把窗簾拿掉就好", "expected_routing": "design_adjuster"},
    {"name": "床邊加小夜燈", "prompt": "床的右邊加一個小夜燈", "expected_routing": "design"},
    {"name": "窗邊加單人椅", "prompt": "在窗邊多放一張單人椅", "expected_routing": "design"},
    {"name": "移動書桌", "prompt": "把書桌移到窗邊", "expected_routing": "design"},
    {"name": "整體改深色系", "prompt": "整體改成深色系", "expected_routing": "design"},
    {"name": "天花板加燈", "prompt": "在天花板加一盞燈", "expected_routing": "design"},
    {"name": "指定床跟書桌位置", "prompt": "床放右邊、書桌在床的左邊", "expected_routing": "design"},
    {"name": "窗簾換米色", "prompt": "把窗簾換成米色的", "expected_routing": "design_adjuster"},
    {"name": "移除掛畫", "prompt": "把電視牆上的畫框拿掉", "expected_routing": "design_adjuster"},
    {"name": "沙發旁加立燈", "prompt": "沙發旁邊加一個立燈", "expected_routing": "design"},
    {"name": "衣櫃門片換色", "prompt": "把衣櫃的門片換成白色", "expected_routing": "design_adjuster"},
    {"name": "氣氛微調", "prompt": "氣氛溫馨一點，燈光暖一些", "expected_routing": "design"},
    {"name": "客廳動線重排", "prompt": "客廳動線想重新安排一下", "expected_routing": "design"},
]


# ── Backend 1：Gemini（完全重用 production 路徑，不是另外模擬） ─────────────────
def call_gemini_ra(text_prompt: str) -> dict[str, Any]:
    """呼叫跟正式系統一模一樣的 RA 程式碼路徑。失敗（含 JSON 解析失敗）直接拋出例外，
    由呼叫端記錄成 parsed_ok=False，不吞掉、不 fallback，這樣消融比較的解析成功率
    才是真實數字。"""
    req = _call_llm_requirement_analyzer(text_prompt, "無")
    return {"routing_decision": req.get("_routing_decision", "design"), "raw": req}


# ── Backend 2：ITRI vLLM 端點上的模型（例如 gpt-oss-120b） ───────────────────────
def _clean_and_parse_json(text: str) -> dict[str, Any]:
    """跟 requirement.py 的 _call_llm_requirement_analyzer 完全一樣的清洗規則
    （去 markdown fence、抓 {...} 範圍、json.loads），確保兩個 backend 是用
    同一套解析容忍度在評分，比較才公平。"""
    text = (text or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if not text.startswith("{"):
        start = text.find("{")
        if start != -1:
            text = text[start:]
    if not text.endswith("}"):
        end = text.rfind("}")
        if end != -1:
            text = text[: end + 1]
    return json.loads(text)


def call_vllm_ra(text_prompt: str, base_url: str, model_name: str) -> dict[str, Any]:
    """透過 OpenAI 相容 API 打 vLLM 端點，重用跟 production 完全一樣的 RA prompt
    模板，確保兩邊拿到的題目一模一樣。"""
    from openai import OpenAI

    prompt = REQUIREMENT_ANALYZER_PROMPT.format(text_prompt=text_prompt, initial_image="無")
    client = OpenAI(base_url=base_url, api_key="dummy-key")
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=Config.GEMINI_TEMPERATURE,  # 跟 Gemini 那邊同溫度，比較才公平
        # gpt-oss 這類推理模型會把隱藏思考也算進同一個 token 預算裡（跟這個專案
        # 稍早在 composer.py 踩到的 Gemini 3.x thinking-token 截斷是同一類問題），
        # 給足夠大的上限，避免真正的 JSON 輸出被隱藏推理擠到只剩半句。
        max_tokens=2000,
    )
    message = response.choices[0].message
    text = message.content
    if not text:
        reasoning = getattr(message, "reasoning", None)
        raise ValueError(
            f"空回應（finish_reason={response.choices[0].finish_reason}, "
            f"reasoning={str(reasoning)[:200]!r}）"
        )
    parsed = _clean_and_parse_json(text)
    if "structured_requirement" not in parsed or "routing_decision" not in parsed:
        raise ValueError(f"缺少必要欄位（拿到的 keys: {list(parsed.keys())}）")
    routing = parsed["routing_decision"]
    if routing not in _VALID_ROUTING_DECISIONS:
        routing = "design"
    return {"routing_decision": routing, "raw": parsed}


def probe_vllm_model(base_url: str, default_model: str) -> str:
    """打 /models 確認端點活著、抓實際掛載的模型名稱，抓不到就用預設值（跟範例
    筆記本的檢查方式一樣）。"""
    import requests

    try:
        resp = requests.get(base_url.rstrip("/") + "/models", timeout=10)
        data = resp.json()
        models = data.get("data") or []
        if models:
            model_id = models[0]["id"]
            print(f"✅ vLLM 端點存活，實際模型：{model_id}")
            return model_id
    except Exception as e:
        print(f"⚠️  無法探測 vLLM 端點模型清單（{e}），使用預設值：{default_model}")
    return default_model


# ── 單一案例執行 + 記錄 ──────────────────────────────────────────────────────────
def run_case(case: dict[str, str], backend_fn, backend_name: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        result = backend_fn(case["prompt"])
        elapsed = time.perf_counter() - t0
        actual = result["routing_decision"]
        return {
            "backend": backend_name,
            "case": case["name"],
            "prompt": case["prompt"],
            "expected": case["expected_routing"],
            "actual": actual,
            "match": actual == case["expected_routing"],
            "parsed_ok": True,
            "latency_s": round(elapsed, 2),
            "error": None,
        }
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {
            "backend": backend_name,
            "case": case["name"],
            "prompt": case["prompt"],
            "expected": case["expected_routing"],
            "actual": None,
            "match": False,
            "parsed_ok": False,
            "latency_s": round(elapsed, 2),
            "error": f"{type(e).__name__}: {e}",
        }


def summarize(results: list[dict[str, Any]], backend_name: str) -> dict[str, Any]:
    rows = [r for r in results if r["backend"] == backend_name]
    n = len(rows)
    parsed = [r for r in rows if r["parsed_ok"]]
    return {
        "backend": backend_name,
        "n": n,
        "routing_accuracy": sum(r["match"] for r in rows) / n if n else 0.0,
        "parse_success_rate": len(parsed) / n if n else 0.0,
        "avg_latency_s": statistics.mean(r["latency_s"] for r in rows) if rows else 0.0,
    }


def print_comparison_table(summaries: list[dict[str, Any]]) -> None:
    print(f"\n{'='*72}")
    print("消融比較結果")
    print(f"{'='*72}")
    header = f"{'Backend':<28} {'路由準確率':>10} {'JSON解析成功率':>14} {'平均延遲(s)':>12}"
    print(header)
    print("-" * len(header))
    for s in summaries:
        print(
            f"{s['backend']:<28} {s['routing_accuracy']*100:>9.1f}% "
            f"{s['parse_success_rate']*100:>13.1f}% {s['avg_latency_s']:>12.2f}"
        )


# ── CLI 模式 ─────────────────────────────────────────────────────────────────
def run_batch(cases: list[dict[str, str]] = BATCH_CASES) -> None:
    """跑內建案例，backend 固定 Gemini（production 路徑）。"""
    print(f"\n{'='*60}\n批次測試：共 {len(cases)} 個案例（Gemini）\n{'='*60}")
    results = [run_case(c, call_gemini_ra, "gemini") for c in cases]
    for r in results:
        status = "✅" if r["parsed_ok"] else "❌"
        match = "match" if r["match"] else "MISMATCH"
        print(f"{status} [{r['case']}] expected={r['expected']} actual={r['actual']} ({match}, {r['latency_s']}s)")
        if r["error"]:
            print(f"   error: {r['error']}")
    summary = summarize(results, "gemini")
    print_comparison_table([summary])
    _save_results(results, "batch_gemini")


def run_single_test(prompt: str) -> None:
    print(f"\n{'─'*60}\n📝 指令：{prompt}\n{'─'*60}")
    try:
        req = _call_llm_requirement_analyzer(prompt, "無")
        print(json.dumps(req, ensure_ascii=False, indent=2))
        print(f"\n🗺️  routing_decision → {req.get('_routing_decision')}")
    except Exception as e:
        print(f"❌ 失敗：{type(e).__name__}: {e}")


def run_compare(
    cases: list[dict[str, str]],
    vllm_base_url: str,
    vllm_model: str,
    repeats: int,
) -> None:
    model_id = probe_vllm_model(vllm_base_url, vllm_model)

    all_results: list[dict[str, Any]] = []
    total = len(cases) * repeats
    done = 0
    for rep in range(repeats):
        for case in cases:
            done += 1
            print(f"[{done}/{total*2}] gemini    | {case['name']}")
            all_results.append(run_case(case, call_gemini_ra, "gemini"))
            done += 1
            print(f"[{done}/{total*2}] {model_id:<10}| {case['name']}")
            all_results.append(
                run_case(
                    case,
                    lambda p: call_vllm_ra(p, vllm_base_url, model_id),
                    model_id,
                )
            )

    summaries = [summarize(all_results, "gemini"), summarize(all_results, model_id)]
    print_comparison_table(summaries)
    _save_results(all_results, "compare_gemini_vs_" + model_id.replace("/", "_"))


def _save_results(results: list[dict[str, Any]], slug: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"{slug}_{timestamp}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 完整結果已存：{out_path.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description="測試 / 消融比較 DesignBridge Requirement Analyzer")
    parser.add_argument("--prompt", "-p", type=str, help="單一設計指令文字（走 Gemini production 路徑）")
    parser.add_argument("--batch", "-b", action="store_true", help="跑內建批次測試案例（Gemini）")
    parser.add_argument("--compare", "-c", action="store_true", help="消融比較：同一組案例跑 Gemini + vLLM 端點")
    parser.add_argument("--repeats", type=int, default=1, help="--compare 模式下每條案例重跑幾次取平均（預設 1）")
    parser.add_argument("--vllm-base-url", type=str, default=DEFAULT_VLLM_BASE_URL, help="vLLM OpenAI 相容端點 base_url")
    parser.add_argument("--vllm-model", type=str, default=DEFAULT_VLLM_MODEL, help="探測失敗時使用的預設模型名稱")
    args = parser.parse_args()

    if args.compare:
        run_compare(BATCH_CASES, args.vllm_base_url, args.vllm_model, args.repeats)
    elif args.batch:
        run_batch()
    elif args.prompt:
        run_single_test(args.prompt)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

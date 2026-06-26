import os, json, time
from llm import get_deepseek_answer

SYSTEM_PROMPT = "You are an expert ArkTS repair assistant. Fix defects and output ONLY the fixed code."
PROBLEM_DIR = "data/pairs/problem_code"
EXPECTED_DIR = "data/pairs/repair_code"
OUTPUT_DIR = "comparison_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def extract_code(response):
    if not response:
        return ""
    code = response.strip()
    if "```" in code:
        code = code.split("```")[1]
        if '\n' in code:
            code = code[code.index('\n')+1:]
    return code.strip()

all_files = sorted([f for f in os.listdir(PROBLEM_DIR) if f.endswith('.ets')])
print(f"Testing {len(all_files)} defect files from problem_code/\n")

results = []
start = time.time()

for i, fname in enumerate(all_files):
    with open(os.path.join(PROBLEM_DIR, fname), 'r', encoding='utf-8') as f:
        defect_code = f.read()

    with open(os.path.join(EXPECTED_DIR, fname), 'r', encoding='utf-8') as f:
        expected_code = f.read()

    rule = fname.rsplit('_', 1)[0]

    prompt = f"Fix defects in this ArkTS code:\n```\n{defect_code}\n```"
    resp = get_deepseek_answer(prompt, system_prompt=SYSTEM_PROMPT, model_name="deepseek-chat")
    fixed = extract_code(resp)

    out_path = os.path.join(OUTPUT_DIR, fname.replace('.ets', '_fixed.ets'))
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fixed)

    # Compare with expected
    diff_with_original = (fixed.strip() != defect_code.strip())
    diff_with_expected = (fixed.strip() == expected_code.strip())

    results.append({
        "file": fname,
        "rule": rule,
        "original_len": len(defect_code),
        "fixed_len": len(fixed),
        "expected_len": len(expected_code),
        "changed_from_original": diff_with_original,
        "matches_expected": diff_with_expected,
    })

    if (i + 1) % 30 == 0:
        e = time.time() - start
        print(f"[{i+1}/{len(all_files)}] {e:.0f}s elapsed...")

# Summary
total = len(results)
exact_match = sum(1 for r in results if r['matches_expected'])
changed = sum(1 for r in results if r['changed_from_original'])
no_change = sum(1 for r in results if not r['changed_from_original'])

print(f"\n{'='*60}")
print(f"RESULTS")
print(f"{'='*60}")
print(f"Total defect files tested:    {total}")
print(f"Changed (fix applied):        {changed}  ({changed/total*100:.1f}%)")
print(f"No change needed:             {no_change}  ({no_change/total*100:.1f}%)")
print(f"Exact match with expected:    {exact_match}  ({exact_match/total*100:.1f}%)")

# By rule
rule_stats = {}
for r in results:
    rule = r['rule']
    if rule not in rule_stats:
        rule_stats[rule] = {"total": 0, "matched": 0, "changed": 0}
    rule_stats[rule]["total"] += 1
    if r['matches_expected']:
        rule_stats[rule]["matched"] += 1
    if r['changed_from_original']:
        rule_stats[rule]["changed"] += 1

print(f"\n{'='*60}")
print(f"BY RULE")
print(f"{'='*60}")
for rule, s in sorted(rule_stats.items()):
    if s['total'] > 1:
        m = s['matched']/s['total']*100
        c = s['changed']/s['total']*100
        print(f"  {rule}: {s['changed']}/{s['total']} fixed ({c:.0f}%), {s['matched']}/{s['total']} exact ({m:.0f}%)")
    else:
        m = s['matched']/s['total']*100
        print(f"  {rule}: {'✓' if s['matched'] else ' '} {s['changed']}/{s['total']} ({m:.0f}%)")

with open(os.path.join(OUTPUT_DIR, "results.json"), 'w', encoding='utf-8') as f:
    json.dump({
        "total": total, "exact_match": exact_match,
        "changed": changed, "unchanged": no_change,
        "change_rate_pct": round(changed/total*100, 1),
        "exact_match_rate_pct": round(exact_match/total*100, 1),
        "by_rule": {k: {"total": v["total"], "matched": v["matched"], "changed": v["changed"]}
                    for k, v in rule_stats.items()},
        "details": results,
    }, f, ensure_ascii=False, indent=2)

elapsed = time.time() - start
print(f"\nTotal time: {elapsed:.0f}s")
print(f"Fixed files: {OUTPUT_DIR}/")
print(f"Report: {OUTPUT_DIR}/results.json")

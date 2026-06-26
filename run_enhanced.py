import os, json, time
from llm import get_deepseek_answer

SYSTEM_PROMPT = "You are an expert ArkTS repair assistant. Fix defects and output ONLY the fixed code."
PROBLEM_DIR = "data/pairs/problem_code"
EXPECTED_DIR = "data/pairs/repair_code"
OUTPUT_DIR = "comparison_enhanced"
RULES_FILE = "data/test.csv"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load rule descriptions
import csv
rule_desc = {}
with open(RULES_FILE, 'r', encoding='utf-8') as f:
    for row in csv.reader(f):
        if len(row) >= 2:
            rule_desc[row[0].strip()] = row[1].strip()

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
print(f"Enhanced test: {len(all_files)} files\n")

results = []
start = time.time()

for i, fname in enumerate(all_files):
    with open(os.path.join(PROBLEM_DIR, fname), 'r', encoding='utf-8') as f:
        defect_code = f.read()

    with open(os.path.join(EXPECTED_DIR, fname), 'r', encoding='utf-8') as f:
        expected_code = f.read()

    rule = fname.rsplit('_', 1)[0]
    desc = rule_desc.get(rule, "")

    # Enhanced prompt with rule description (simulates RAG context)
    prompt = f"""Defect Rule: {rule}
Description: {desc}

Fix defects in this ArkTS code:
```\n{defect_code}\n```"""

    resp = get_deepseek_answer(prompt, system_prompt=SYSTEM_PROMPT, model_name="deepseek-chat")
    fixed = extract_code(resp)

    out_path = os.path.join(OUTPUT_DIR, fname.replace('.ets', '_fixed.ets'))
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fixed)

    diff_with_original = (fixed.strip() != defect_code.strip())
    diff_with_expected = (fixed.strip() == expected_code.strip())

    results.append({
        "file": fname, "rule": rule,
        "changed_from_original": diff_with_original,
        "matches_expected": diff_with_expected,
    })

    if (i + 1) % 30 == 0:
        print(f"[{i+1}/{len(all_files)}] ...")

# Summary
total = len(results)
exact_match = sum(1 for r in results if r['matches_expected'])
changed = sum(1 for r in results if r['changed_from_original'])
no_change = sum(1 for r in results if not r['changed_from_original'])

print(f"\n{'='*60}")
print(f"ENHANCED RESULTS (with rule context)")
print(f"{'='*60}")
print(f"Total:               {total}")
print(f"Fixed:               {changed}  ({changed/total*100:.1f}%)")
print(f"No change:           {no_change}  ({no_change/total*100:.1f}%)")
print(f"Exact match:         {exact_match}  ({exact_match/total*100:.1f}%)")

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

print(f"\nBY RULE:")
for rule, s in sorted(rule_stats.items()):
    if s['total'] > 1:
        m = s['matched']/s['total']*100
        c = s['changed']/s['total']*100
        print(f"  {rule}: {s['changed']}/{s['total']} fixed ({c:.0f}%), {s['matched']}/{s['total']} exact ({m:.0f}%)")

with open(os.path.join(OUTPUT_DIR, "results.json"), 'w', encoding='utf-8') as f:
    json.dump({
        "total": total, "exact_match": exact_match,
        "changed": changed, "unchanged": no_change,
        "by_rule": rule_stats, "details": results,
    }, f, ensure_ascii=False, indent=2)

elapsed = time.time() - start
print(f"\nTime: {elapsed:.0f}s")
print(f"Output: {OUTPUT_DIR}/")

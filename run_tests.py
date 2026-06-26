import csv
import json
import os
from llm import get_deepseek_answer

SYSTEM_PROMPT = "You are an expert ArkTS repair assistant. Output ONLY the fixed code."
OUTPUT_DIR = "repair_results"

def extract_code(response):
    if not response:
        return ""
    code = response.strip()
    if "```" in code:
        code = code.split("```")[1]
        if '\n' in code:
            code = code[code.index('\n')+1:]
    return code.strip()

os.makedirs(OUTPUT_DIR, exist_ok=True)

csv_path = os.path.join("data", "test.csv")
with open(csv_path, 'r', encoding='utf-8') as f:
    rows = list(csv.reader(f))

results = []
for i, row in enumerate(rows[1:], 1):
    rule = row[0]
    code = row[2] if len(row) > 2 else ""

    rule_name = rule.replace("@", "").replace("/", "_").strip().split("\n")[0]
    output_file = os.path.join(OUTPUT_DIR, f"{i:02d}_{rule_name}_fixed.ets")

    prompt = f"Fix defects in this ArkTS code:\n```\n{code}\n```"
    resp = get_deepseek_answer(prompt, system_prompt=SYSTEM_PROMPT, model_name="deepseek-chat")
    fixed = extract_code(resp)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(fixed)

    results.append({
        "id": i,
        "rule": rule,
        "source": "data/test.csv",
        "fixed_file": output_file,
        "original_length": len(code),
        "fixed_length": len(fixed),
    })
    print(f"[{i}/6] {rule} -> {output_file}")

with open(os.path.join(OUTPUT_DIR, "summary.json"), 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nDone! {len(results)} files saved to {OUTPUT_DIR}/")
print(f"Summary: {OUTPUT_DIR}/summary.json")

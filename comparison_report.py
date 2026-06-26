import json, os

# Load results
with open("comparison_results/results.json") as f:
    base = json.load(f)
with open("comparison_enhanced/results.json") as f:
    enhanced = json.load(f)

print("="*70)
print("COMPARISON REPORT: Baseline vs Enhanced (with Context)")
print("="*70)
print()
print(f"{'Metric':<40} {'Baseline':<15} {'Enhanced':<15} {'Change':<10}")
print("-"*70)
print(f"{'Total files tested':<40} {'266':<15} {'266':<15} {'-':<10}")
print(f"{'Fixed (change detected)':<40} {f'227 (85.3%)':<15} {f'248 (93.2%)':<15} {'+7.9%':<10}")
print(f"{'Not changed':<40} {f'39 (14.7%)':<15} {f'18 (6.8%)':<15} {'-7.9%':<10}")
print(f"{'Exact match with expected':<40} {f'3 (1.1%)':<15} {f'7 (2.6%)':<15} {'+1.5%':<10}")
print()

# By rule comparison
print("="*70)
print("BY RULE COMPARISON")
print("="*70)
print(f"{'Rule':<45} {'Baseline':<12} {'Enhanced':<12} {'Improve':<10}")
print("-"*70)

rules = sorted(set(list(base.get('by_rule', {}).keys()) + list(enhanced.get('by_rule', {}).keys())))
for rule in rules:
    b = base.get('by_rule', {}).get(rule, {"total": 0, "changed": 0})
    e = enhanced.get('by_rule', {}).get(rule, {"total": 0, "changed": 0})
    b_total = b.get('total', 0)
    b_fixed = b.get('changed', 0)
    e_total = e.get('total', 0)
    e_fixed = e.get('changed', 0)
    
    if b_total > 0:
        b_pct = b_fixed / b_total * 100
        e_pct = e_fixed / e_total * 100 if e_total > 0 else 0
        delta = e_pct - b_pct
        delta_str = f"+{delta:.0f}%" if delta > 0 else f"{delta:.0f}%"
        print(f"{rule:<45} {b_fixed}/{b_total:<7} {e_fixed}/{e_total:<7} {delta_str:<10}")

print()
print("="*70)
print("SUMMARY")
print("="*70)
print("1. Baseline (direct DeepSeek repair without context):")
print("   85.3% of defect files were modified by the LLM")
print()
print("2. Enhanced (with rule description context):")
print("   93.2% of defect files were modified (+7.9% improvement)")
print()
print("3. Exact match with expected repair:")
print("   Baseline: 1.1% vs Enhanced: 2.6%")
print()
print("NOTE: The cross-file dependency module (cross_file_dependency.py)")
print("requires full project context to analyze inter-file dependencies.")
print("These 266 files are individual snippets, so cross-file analysis")
print("cannot be directly applied here. The comparison above shows the")
print("improvement from adding rule context (simulating RAG context).")
print()
print("To test cross-file dependency benefits, we need actual")
print("OpenHarmony projects (the paper's 35 projects with 8,664 defects).")

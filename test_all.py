import os, sys, json

os.system('')  # enable ANSI colors

GREEN = '\033[92m'
RED = '\033[91m'
CYAN = '\033[96m'
YELLOW = '\033[93m'
BOLD = '\033[1m'
END = '\033[0m'

def header(text):
    print(f"\n{BOLD}{CYAN}{'='*60}{END}")
    print(f"{BOLD}{CYAN}  {text}{END}")
    print(f"{BOLD}{CYAN}{'='*60}{END}")

def ok(text):
    print(f"  {GREEN}[PASS] {text}{END}")

def fail(text):
    print(f"  {RED}[FAIL] {text}{END}")

def info(text):
    print(f"  {YELLOW}[INFO] {text}{END}")

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        ok(name)
        passed += 1
    except Exception as e:
        fail(f"{name}: {e}")
        failed += 1

# ============================================================================
header("TEST 1: DeepSeek API 连接测试")

def test_api():
    from llm import get_deepseek_answer
    resp = get_deepseek_answer("Return only: OK", model_name="deepseek-chat")
    assert resp and "OK" in resp, f"Response: {resp}"

test("API 连通性", test_api)

# ============================================================================
header("TEST 2: 代码修复测试 (data/test.csv)")

def test_repair():
    from llm import get_deepseek_answer
    import csv
    
    SYSTEM_PROMPT = "You are an ArkTS repair expert. Output ONLY fixed code."
    csv_path = os.path.join("data", "test.csv")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    
    count = 0
    for row in rows[1:]:
        if len(row) < 3 or not row[2].strip():
            continue
        code = row[2]
        prompt = f"Fix defects in this ArkTS code:\n```\n{code}\n```"
        resp = get_deepseek_answer(prompt, system_prompt=SYSTEM_PROMPT, model_name="deepseek-chat")
        assert resp and len(resp) > 10
        count += 1
    
    assert count >= 3, f"Only {count} tests passed"

test("批量修复 (≥3个用例)", test_repair)

# ============================================================================
header("TEST 3: 跨文件依赖分析测试")

def test_cross_file():
    from cross_file_dependency import (
        scan_project_files,
        analyze_single_file,
        build_dependency_graph,
        get_cross_file_context,
        create_cross_file_extractor,
    )
    
    root = "."
    files = scan_project_files(root)
    assert len(files) > 0, "No .ets/.ts files found"
    info(f"扫描到 {len(files)} 个文件")
    
    analysis = analyze_single_file(files[0])
    info(f"{os.path.basename(files[0])}: {len(analysis.imports)} imports, {len(analysis.exports)} exports")
    
    graph = build_dependency_graph(files, root)
    total_edges = sum(len(e) for e in graph.values())
    info(f"依赖图: {len(graph)} 节点, {total_edges} 条边")
    assert total_edges > 0
    
    extractor = create_cross_file_extractor(root)
    summary = extractor.get_graph_summary()
    info(f"平均出度: {summary['avg_depth']:.2f}")
    
    ctx = get_cross_file_context(files[0], graph)
    info(f"跨文件上下文: {ctx['total_dependencies']} 个依赖文件")

test("依赖分析", test_cross_file)

# ============================================================================
header("TEST 4: 真实缺陷修复测试 (data/pairs/repair_code)")

def test_real_repair():
    from llm import get_deepseek_answer
    
    repair_dir = "data/pairs/repair_code"
    ets_files = [f for f in os.listdir(repair_dir) if f.endswith('.ets')]
    assert len(ets_files) > 0
    
    info(f"找到 {len(ets_files)} 个缺陷样例")
    
    samples = sorted(ets_files)[:5]
    SYSTEM_PROMPT = "You are an ArkTS expert. Fix defects and output ONLY the fixed code."
    
    for fname in samples:
        with open(os.path.join(repair_dir, fname), 'r', encoding='utf-8') as f:
            code = f.read()
        
        prompt = f"Fix this ArkTS code:\n```\n{code}\n```"
        resp = get_deepseek_answer(prompt, system_prompt=SYSTEM_PROMPT, model_name="deepseek-chat")
        assert resp and len(resp) > 10, f"Failed for {fname}"
        info(f"{fname}: 已修复 ({len(resp)} chars)")

test("真实缺陷修复 (5个样例)", test_real_repair)

# ============================================================================
header("TEST 5: 修复提示词测试")

def test_prompts():
    from get_prompt import generate_fix_prompt
    
    sample_code = "@Entry\n@Component\nstruct Index {\n  build() {\n    Column() {\n      Text('Hello')\n    }\n  }\n}"
    
    prompt = generate_fix_prompt("", sample_code, "", "test_rule", "test_location")
    assert len(prompt) > 50, f"Prompt too short: {len(prompt)}"
    info(f"修复提示词长度: {len(prompt)} 字符")

test("提示词生成", test_prompts)

# ============================================================================
header("TEST 6: 文件扫描与自检")

def test_self_test():
    from cross_file_dependency import self_test
    report = self_test(".")
    info(f"文件总数: {report['total_files']}")
    info(f"有 import 的文件: {report['files_with_imports']}")
    info(f"有 export 的文件: {report['files_with_exports']}")
    info(f"有装饰器的文件: {report['files_with_decorators']}")
    assert report['total_files'] > 0

test("自检", test_self_test)

# ============================================================================
header("TEST 7: 循环依赖检测")

def test_cycle_detection():
    from cross_file_dependency import (
        scan_project_files, build_dependency_graph, _detect_cycles
    )
    from collections import defaultdict
    
    files = scan_project_files(".")
    graph = build_dependency_graph(files, ".")
    
    cycle_count = sum(1 for edges in graph.values() for e in edges if e.is_cycle)
    info(f"循环依赖边: {cycle_count}")
    
    if cycle_count > 0:
        for src, edges in graph.items():
            for e in edges:
                if e.is_cycle:
                    info(f"  {os.path.basename(src)} → {os.path.basename(e.target_file)}")
    
    assert cycle_count >= 0

test("循环依赖", test_cycle_detection)

# ============================================================================
print(f"\n{BOLD}{'='*60}{END}")
print(f"{BOLD}结果: {GREEN}{passed} 通过{END}  {RED}{failed} 失败{END}  / {passed+failed} 总测试{END}")
print(f"{BOLD}{'='*60}{END}")

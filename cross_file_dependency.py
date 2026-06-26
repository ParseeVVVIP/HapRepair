"""
跨文件依赖分析模块 (Cross-File Dependency Analysis Module)

使用正则表达式进行 ArkTS 文件解析，构建项目级文件依赖图，
提取跨文件修复上下文。是 HapRepair 缺陷上下文提取的增强模块。

架构设计参考：
    pr-claude-01/plans/optimized_cross_file_dependency.md

依赖：
    - Python 标准库 (os, re, collections, dataclasses, typing)
    - 可选：tree-sitter + tree-sitter-typescript（提供更精确的 AST 解析）

用法：
    from cross_file_dependency import (
        scan_project_files,
        analyze_single_file,
        FileAnalysis,
    )

    files = scan_project_files('/path/to/project')
    analysis = analyze_single_file(files[0])
    print(analysis.imports, analysis.exports, analysis.decorators)

作者：HapRepair Team
日期：2026-06-11
"""

import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple

# ============================================================================
# 常量定义
# ============================================================================

# 排除的目录名（不扫描其中的文件）
EXCLUDE_DIRS: Set[str] = {
    'node_modules', 'build', '.git', '__pycache__',
    '.hvigor', 'oh_modules', 'libs', '.preview',
    'venv', '.idea', '.vscode', 'dist',
}

# 扫描的文件扩展名
SCAN_EXTENSIONS: Tuple[str, ...] = ('.ets', '.ts')

# SDK/系统导入前缀（这些不解析为项目内文件依赖）
SDK_IMPORT_PREFIXES: Tuple[str, ...] = (
    '@ohos.', '@kit.', '@hw-', '@system.',
    'ohos.', 'resource://',
)

# ArkTS 装饰器列表
ARKTS_DECORATORS: Set[str] = {
    'Component', 'Entry', 'State', 'Prop', 'Link', 'ObjectLink',
    'Provide', 'Consume', 'Watch', 'StorageLink', 'StorageProp',
    'Builder', 'Extend', 'Styles', 'Observed', 'Track',
}

# 状态变量装饰器（表示组件间的数据流关系）
STATE_DECORATORS: Dict[str, str] = {
    'State': 'state',
    'Prop': 'prop',
    'Link': 'link',
    'ObjectLink': 'object_link',
    'Provide': 'provide',
    'Consume': 'consume',
    'StorageLink': 'storage_link',
    'StorageProp': 'storage_prop',
}


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class FileAnalysis:
    """单文件分析结果"""
    file_path: str
    relative_path: str
    imports: List[Dict] = field(default_factory=list)
    # imports: [{
    #     'module': './MyComponent',      # 原始 import 路径
    #     'symbols': ['MyComponent'],      # 导入的符号列表
    #     'import_type': 'default'|'named'|'namespace',  # 导入类型
    #     'line': 5,                       # 所在行号
    # }]
    exports: List[Dict] = field(default_factory=list)
    # exports: [{
    #     'name': 'MyComponent',           # 导出符号名
    #     'type': 'struct'|'class'|'function'|'variable'|'default_object',
    #     'line': 10,                      # 所在行号
    # }]
    decorators: Dict[str, List[str]] = field(default_factory=dict)
    # decorators: {'MyComponent': ['@Component', '@Entry'], 'count': ['@State']}
    # 键是目标名称（struct/变量名），值是装饰器列表
    state_variables: List[str] = field(default_factory=list)
    # state_variables: ['count', 'message']  — @State 标记的变量名
    prop_variables: List[str] = field(default_factory=list)
    # prop_variables: [...]  — @Prop 标记的变量名
    link_variables: List[str] = field(default_factory=list)
    # link_variables: [...]  — @Link 标记的变量名


@dataclass
class DependencyEdge:
    """依赖图中的有向边"""
    source_file: str       # 源文件路径
    target_file: str       # 目标文件路径
    dep_types: List[str] = field(default_factory=list)
    # dep_types: ['component', 'function', 'data_flow', 'type', 'state_bearing']
    weight: float = 1.0
    symbols: List[str] = field(default_factory=list)
    # symbols: 此边传递的具体符号名
    is_cycle: bool = False
    # is_cycle: 此边是否参与循环依赖（ArkTS 中循环依赖可导致运行时异常）


# ============================================================================
# P0 函数：文件扫描
# ============================================================================

def scan_project_files(project_root: str) -> List[str]:
    """
    扫描项目根目录下的所有 .ets / .ts 文件。

    参数：
        project_root: 项目根目录的绝对路径。

    返回：
        按字母序排序的文件绝对路径列表。

    排除规则：
        - node_modules, build, .git, __pycache__ 等非源码目录
        - 隐藏目录（以 . 开头，但 . 本身除外）
    """
    files: List[str] = []

    project_root = os.path.normpath(os.path.abspath(project_root))

    if not os.path.isdir(project_root):
        raise ValueError(f"Project root does not exist or is not a directory: {project_root}")

    for root, dirs, filenames in os.walk(project_root):
        # 原地修改 dirs，排除不需要的目录
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDE_DIRS and not d.startswith('.')
        ]

        for fname in filenames:
            if fname.endswith(SCAN_EXTENSIONS):
                files.append(os.path.normpath(os.path.join(root, fname)))

    files.sort()
    return files


# ============================================================================
# P0 函数：基于正则的 import / export / 装饰器 解析
# ============================================================================

def parse_imports_exports_via_regex(file_path: str) -> FileAnalysis:
    """
    基于正则表达式的 ArkTS import / export / 装饰器 解析。

    这是 tree-sitter 方案的 fallback。tree-sitter 不可用时使用此函数。

    支持的语法：
        Import:
        - import X from './path'              (default import)
        - import { X } from './path'          (named import)
        - import { X as Y } from './path'     (aliased named import)
        - import * as X from './path'         (namespace import)

        Export:
        - export default class/struct/function X
        - export default { ... }              (default object literal)
        - export default new X()
        - export class/struct/function X
        - export { X, Y }
        - export { X } from './path'          (barrel re-export)

        Decorators:
        - @Component, @Entry, @State, @Prop, @Link, @ObjectLink
        - @Provide, @Consume, @Watch(...), @StorageLink(...), @StorageProp(...)
        - @Builder, @Extend, @Styles, @Observed, @Track

    参数：
        file_path: .ets 或 .ts 文件的绝对路径。

    返回：
        FileAnalysis 对象，包含 imports, exports, decorators 等字段。
    """
    # 读取文件内容
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read()
    except (IOError, OSError) as e:
        print(f"Warning: Could not read file {file_path}: {e}")
        return FileAnalysis(
            file_path=file_path,
            relative_path=os.path.basename(file_path),
        )

    result = FileAnalysis(
        file_path=file_path,
        relative_path=os.path.basename(file_path),
    )

    # ---- 1. Import 解析 ----

    # 1a. Named imports: import { X, Y } from './path'
    #     也匹配: import { X as Y } from './path'
    named_import_re = re.compile(
        r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    for m in named_import_re.finditer(source):
        symbols_str = m.group(1)
        module_path = m.group(2)
        line_num = source[:m.start()].count('\n') + 1

        # 解析花括号内的符号列表
        symbols: List[str] = []
        for part in symbols_str.split(','):
            part = part.strip()
            if not part:
                continue
            # 处理 "X as Y" → 取原始名 X
            if ' as ' in part:
                symbols.append(part.split(' as ')[0].strip())
            else:
                symbols.append(part)

        result.imports.append({
            'module': module_path,
            'symbols': symbols,
            'import_type': 'named',
            'line': line_num,
        })

    # 1b. Namespace imports: import * as X from './path'
    namespace_import_re = re.compile(
        r"import\s*\*\s*as\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    for m in namespace_import_re.finditer(source):
        result.imports.append({
            'module': m.group(2),
            'symbols': [m.group(1)],
            'import_type': 'namespace',
            'line': source[:m.start()].count('\n') + 1,
        })

    # 1c. Default imports: import X from './path'
    #     (必须在 named import 之后，否则会错误匹配)
    default_import_re = re.compile(
        r"import\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    for m in default_import_re.finditer(source):
        result.imports.append({
            'module': m.group(2),
            'symbols': [m.group(1)],
            'import_type': 'default',
            'line': source[:m.start()].count('\n') + 1,
        })

    # ---- 2. Export 解析 ----

    # 2a. export default class/struct/function/const/let X
    export_default_named_re = re.compile(
        r"export\s+default\s+(?:class|struct|function|const|let)\s+(\w+)",
        re.MULTILINE,
    )
    for m in export_default_named_re.finditer(source):
        result.exports.append({
            'name': m.group(1),
            'type': 'default_named',
            'line': source[:m.start()].count('\n') + 1,
        })

    # 2b. export default new X(...)  (在 2c 之前，因为更具体)
    export_default_new_re = re.compile(
        r"export\s+default\s+new\s+(\w+)\s*\([^)]*\)",
        re.MULTILINE,
    )
    for m in export_default_new_re.finditer(source):
        result.exports.append({
            'name': m.group(1),
            'type': 'default_instance',
            'line': source[:m.start()].count('\n') + 1,
        })

    # 2c. export default { ... }  (匿名对象导出)
    export_default_object_re = re.compile(
        r"export\s+default\s*\{",
        re.MULTILINE,
    )
    for m in export_default_object_re.finditer(source):
        result.exports.append({
            'name': '__default_object__',
            'type': 'default_object',
            'line': source[:m.start()].count('\n') + 1,
        })

    # 2d. export class/struct/function X  (非 default 的具名导出)
    export_named_re = re.compile(
        r"export\s+(?:class|struct|function|const|let)\s+(\w+)",
        re.MULTILINE,
    )
    for m in export_named_re.finditer(source):
        name = m.group(1)
        # 防止与 export default 重复
        if not any(e['name'] == name for e in result.exports):
            result.exports.append({
                'name': name,
                'type': 'named',
                'line': source[:m.start()].count('\n') + 1,
            })

    # 2e. export { X, Y }  (命名导出列表)
    export_braced_re = re.compile(
        r"export\s*\{([^}]+)\}",
        re.MULTILINE,
    )
    for m in export_braced_re.finditer(source):
        symbols_str = m.group(1)
        for part in symbols_str.split(','):
            name = part.strip()
            if not name:
                continue
            # 处理 "X as Y"
            if ' as ' in name:
                name = name.split(' as ')[1].strip()
            if not any(e['name'] == name for e in result.exports):
                result.exports.append({
                    'name': name,
                    'type': 'named',
                    'line': source[:m.start()].count('\n') + 1,
                })

    # 2f. export { X } from './path'  (barrel re-export)
    export_re_export_re = re.compile(
        r"export\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    for m in export_re_export_re.finditer(source):
        symbols_str = m.group(1)
        module_path = m.group(2)
        for part in symbols_str.split(','):
            name = part.strip()
            if not name:
                continue
            if ' as ' in name:
                name = name.split(' as ')[1].strip()
            result.exports.append({
                'name': name,
                'type': 're_export',
                'module': module_path,
                'line': source[:m.start()].count('\n') + 1,
            })

    # ---- 3. 装饰器解析 ----

    # 策略分两个阶段：
    #   阶段 A：找所有 @装饰器 的位置
    #   阶段 B：从每个装饰器位置向后搜索（最多 300 字符窗口），寻找关联的目标名
    #
    #   ArkTS 中装饰器有两种常见模式：
    #   模式 1（有声明关键字）：@Entry\n@Component\nstruct MyComponent { ... }
    #   模式 2（无声明关键字）：@State count: number = 0   （struct 中的状态变量）
    #
    #   为避免装饰器误匹配到远处不相关的标识符（如 @State 跳 90 行匹配到 let url），
    #   窗口限制为 300 字符——这对于 struct 内变量声明和相关 struct 都已足够。

    MAX_DECORATOR_WINDOW = 300

    deco_pattern = re.compile(
        r"@(" + "|".join(ARKTS_DECORATORS) + r")\s*(?:\([^)]*\))?",
        re.MULTILINE,
    )

    # 模式 1：有声明关键字（class/struct/function/const/let/var）
    #   例：@Component\nstruct MyComp { ... }
    target_with_keyword_re = re.compile(
        r"(?:\s*@\w+(?:\([^)]*\))?)*\s*"       # 跳过更多堆叠的装饰器
        r"(?:export\s+)?"                        # 可选的 export
        r"(?:default\s+)?"                       # 可选的 default
        r"(?:class|struct|function|const|let|var)\s+"  # 声明关键字
        r"(\w+)",                                # 目标名称
    )

    # 模式 2：无声明关键字（ArkTS struct 内的 @State/@Prop/@Link 等变量）
    #   例：@State count: number = 0
    #   例：@Prop title: string
    target_without_keyword_re = re.compile(
        r"\s*(\w+)\s*[:=]",                      # 标识符后紧跟 : 或 =
    )

    for deco_match in deco_pattern.finditer(source):
        deco_base = deco_match.group(1)
        deco_name = f"@{deco_base}"
        deco_end = deco_match.end()

        # 截取搜索窗口（最多 300 字符）
        window = source[deco_end:deco_end + MAX_DECORATOR_WINDOW]

        target_name: Optional[str] = None

        # 先尝试模式 1（有声明关键字）
        m1 = target_with_keyword_re.match(window)
        if m1:
            target_name = m1.group(1)
        else:
            # 再尝试模式 2（无声明关键字，如 @State count: number）
            m2 = target_without_keyword_re.match(window)
            if m2:
                target_name = m2.group(1)

        if target_name is None:
            continue

        if target_name not in result.decorators:
            result.decorators[target_name] = []
        if deco_name not in result.decorators[target_name]:
            result.decorators[target_name].append(deco_name)

        # 追踪状态变量
        if deco_base == 'State':
            if target_name not in result.state_variables:
                result.state_variables.append(target_name)
        elif deco_base == 'Prop':
            if target_name not in result.prop_variables:
                result.prop_variables.append(target_name)
        elif deco_base == 'Link':
            if target_name not in result.link_variables:
                result.link_variables.append(target_name)

    # 按行号排序
    result.imports.sort(key=lambda x: x['line'])
    result.exports.sort(key=lambda x: x['line'])

    return result


# ============================================================================
# P0 函数：单文件分析入口
# ============================================================================

def analyze_single_file(file_path: str) -> FileAnalysis:
    """
    解析单个 ArkTS / TypeScript 文件。

    优先使用 tree-sitter（如果已安装），fallback 到正则。

    参数：
        file_path: .ets 或 .ts 文件的绝对路径。

    返回：
        FileAnalysis 对象。
    """
    # 尝试 tree-sitter（当前阶段仅提供接口，tree-sitter 实现见 P1）
    # if HAS_TREE_SITTER:
    #     result = parse_imports_exports_via_treesitter(file_path)
    #     if result is not None:
    #         return result

    return parse_imports_exports_via_regex(file_path)


# ============================================================================
# P0 函数：import 路径解析
# ============================================================================

def resolve_import_path(
    current_file: str,
    import_module: str,
    project_root: str,
) -> Optional[str]:
    """
    将 import 路径解析为项目内文件的绝对路径。

    参数：
        current_file: 当前文件的绝对路径。
        import_module: import 语句中的模块路径（如 './MyComponent'）。
        project_root: 项目根目录。

    返回：
        解析后的绝对路径，或 None（SDK 导入 / 无法解析）。
    """
    # 规范化路径（消除 Windows/Linux 差异）
    current_file = os.path.normpath(current_file)

    # 跳过 SDK / 系统导入
    if import_module.startswith(SDK_IMPORT_PREFIXES):
        return None

    # 跳过明显的外部包（不以 . 或 / 开头）
    if not import_module.startswith(('.', '/')):
        # 可能是 npm 包或 SDK 包（如 'ohos.xxx' 不带 @）
        return None

    current_dir = os.path.dirname(current_file)

    # 相对路径解析
    if import_module.startswith('./') or import_module.startswith('../'):
        resolved = os.path.normpath(os.path.join(current_dir, import_module))

        # 尝试添加扩展名
        for ext in ['.ets', '.ts', '/index.ets', '/index.ts']:
            candidate = resolved + ext
            if os.path.exists(candidate):
                return os.path.normpath(candidate)

        # 无扩展名的文件（极少见，但做 fallback）
        if os.path.exists(resolved) and os.path.isfile(resolved):
            return os.path.normpath(resolved)

    return None


# ============================================================================
# 自检函数：验证模块基本可用
# ============================================================================

def self_test(project_root: str) -> Dict:
    """
    在给定项目根目录上运行基本检查，验证模块是否正常工作。

    参数：
        project_root: 项目根目录路径。

    返回：
        包含统计信息的字典。
    """
    report: Dict = {
        'project_root': project_root,
        'total_files': 0,
        'files_with_imports': 0,
        'files_with_exports': 0,
        'files_with_decorators': 0,
        'total_imports': 0,
        'total_exports': 0,
        'errors': [],
    }

    try:
        files = scan_project_files(project_root)
    except ValueError as e:
        report['errors'].append(str(e))
        return report

    report['total_files'] = len(files)

    for fpath in files:
        try:
            analysis = analyze_single_file(fpath)
        except Exception as e:
            report['errors'].append(f"Failed to analyze {fpath}: {e}")
            continue

        if analysis.imports:
            report['files_with_imports'] += 1
            report['total_imports'] += len(analysis.imports)
        if analysis.exports:
            report['files_with_exports'] += 1
            report['total_exports'] += len(analysis.exports)
        if analysis.decorators:
            report['files_with_decorators'] += 1

    return report


# ============================================================================
# P0/P1 函数：依赖图构建
# ============================================================================

def _infer_dependency_types(
    imp: Dict,
    target_analysis: Optional[FileAnalysis],
) -> List[str]:
    """
    推断一条 import 边的依赖类型。

    参数：
        imp: import 信息字典（来自 FileAnalysis.imports）。
        target_analysis: 目标文件的 FileAnalysis（如果目标文件在项目内）。

    返回：
        依赖类型列表，如 ['component']、['function']、['type'] 等。
    """
    types: List[str] = []
    module_path = imp.get('module', '')
    symbols = imp.get('symbols', [])

    # 启发式 1：路径包含 Component/Page/View 等关键词
    component_keywords = [
        'Component', 'Page', 'View', 'Item', 'Panel', 'Dialog',
        'Builder', 'Card', 'Cell', 'Row', 'Column',
    ]
    if any(kw in module_path for kw in component_keywords):
        types.append('component')

    # 启发式 2：检查目标文件的导出类型和装饰器
    if target_analysis:
        exported_names = {e['name'] for e in target_analysis.exports}
        for sym in symbols:
            if sym in exported_names:
                decos = target_analysis.decorators.get(sym, [])
                if any(d in ['@Component', '@Entry'] for d in decos):
                    if 'component' not in types:
                        types.append('component')
                if any(d in ['@State', '@Prop', '@Link'] for d in decos):
                    if 'state_bearing' not in types:
                        types.append('state_bearing')

    # 启发式 3：类型导入（以 I 开头、以 Type/Interface 结尾）
    if any(
        sym.startswith('I') or sym.endswith('Type') or sym.endswith('Interface')
        for sym in symbols
    ):
        types.append('type')

    # 默认
    if not types:
        types.append('function')

    return list(set(types))


def _assign_weights(graph: Dict[str, List[DependencyEdge]]) -> None:
    """
    为依赖图中的边赋值权重（原地修改）。

    权重策略：
        - component 依赖：1.5（组件间的修复最需要上下文）
        - state_bearing 依赖：1.3（状态传递需要关注）
        - function 依赖：1.0（默认）
        - type 依赖（纯类型）：0.5（大多数情况下不需要上下文）
    """
    for edges in graph.values():
        for edge in edges:
            weight = 1.0

            if 'component' in edge.dep_types:
                weight = 1.5
            elif 'state_bearing' in edge.dep_types:
                weight = 1.3
            elif 'function' in edge.dep_types:
                weight = 1.0
            elif 'type' in edge.dep_types and len(edge.dep_types) == 1:
                weight = 0.5

            edge.weight = weight


def _detect_cycles(graph: Dict[str, List[DependencyEdge]]) -> None:
    """
    使用三色 DFS 检测循环依赖并标记参与循环的边（原地修改）。

    为什么必须检测循环依赖：
        - ArkTS 遵循 ECMAScript 模块规范，循环依赖会破坏模块初始化顺序。
        - 典型场景：A.ets import B.ets 的 foo，B.ets import A.ets 的 bar。
          若 B.ets 先执行，调用 foo 时 foo 尚未初始化 → ReferenceError 运行时崩溃。
        - DevEco Studio Code Linter 已内置 @security/no-cycle: "error" 规则。
        - HAR/HSP 包明确禁止循环依赖。
        - 修复操作若涉及循环依赖链上的文件，LLM 必须在 Prompt 中被警告。

    算法：三色标记 DFS
        WHITE (0) — 未访问
        GRAY  (1) — 正在访问（在当前递归栈中）
        BLACK (2) — 已完成访问

    参考来源：
        pr-claude-01/plans/optimized_cross_file_dependency.md
        .claude/deveco_feedbacks/cross_file_dependency_feature.md
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = defaultdict(lambda: WHITE)

    def dfs(node: str, path: List[str]) -> bool:
        """返回 True 表示从 node 出发发现了循环。"""
        color[node] = GRAY
        path.append(node)
        found_cycle = False

        for edge in graph.get(node, []):
            target = edge.target_file
            if color[target] == GRAY:
                # 发现后向边 → 循环依赖！
                edge.is_cycle = True
                found_cycle = True
            elif color[target] == WHITE:
                if dfs(target, path):
                    edge.is_cycle = True
                    found_cycle = True

        path.pop()
        color[node] = BLACK
        return found_cycle

    for node in list(graph.keys()):
        if color[node] == WHITE:
            dfs(node, [])


def build_dependency_graph(
    all_files: List[str],
    project_root: str,
) -> Dict[str, List[DependencyEdge]]:
    """
    构建项目级文件依赖图。

    流程：
        1. 解析所有文件的 import/export/装饰器
        2. 为每个 import 解析目标文件路径，建立依赖边
        3. 推断依赖类型
        4. 赋值权重
        5. 三色 DFS 检测循环依赖

    参数：
        all_files: 项目内所有 .ets/.ts 文件的绝对路径列表。
        project_root: 项目根目录。

    返回：
        邻接表形式的依赖图：{source_file: [DependencyEdge, ...]}
        键为所有文件（包括没有出边的文件）。
    """
    # 初始化邻接表（确保所有文件都作为 key 出现）
    graph: Dict[str, List[DependencyEdge]] = defaultdict(list)
    for f in all_files:
        graph[f] = []  # 确保每个文件都有条目

    file_analysis_map: Dict[str, FileAnalysis] = {}

    # 第一步：解析所有文件
    for file_path in all_files:
        file_analysis_map[file_path] = analyze_single_file(file_path)

    # 第二步：构建依赖边
    for file_path, analysis in file_analysis_map.items():
        for imp in analysis.imports:
            target_file = resolve_import_path(
                file_path, imp['module'], project_root,
            )
            if target_file is None:
                continue  # SDK 导入或无法解析

            # 确保目标文件在项目内
            if target_file not in file_analysis_map:
                continue

            # 推断依赖类型
            dep_types = _infer_dependency_types(
                imp, file_analysis_map.get(target_file),
            )

            edge = DependencyEdge(
                source_file=file_path,
                target_file=target_file,
                dep_types=dep_types,
                symbols=imp.get('symbols', []),
            )
            graph[file_path].append(edge)

    # 第三步：检测循环依赖
    _detect_cycles(graph)

    # 第四步：赋值权重
    _assign_weights(graph)

    return dict(graph)


# ============================================================================
# P1 函数：图优化
# ============================================================================

def optimize_dependency_graph(
    graph: Dict[str, List[DependencyEdge]],
) -> Dict[str, List[DependencyEdge]]:
    """
    优化依赖图：调整边权重以控制上下文提取的优先级。

    策略（不删除任何边，只调整权重）：
        - 纯类型导入（type-only）降权为 0.3
        - 数据流边升权为 1.5
        - 循环依赖边额外 +0.2 权重，提升其在 Prompt 中的可见性
        - 归一化到 [0.1, 2.0]

    参数：
        graph: build_dependency_graph() 的输出。

    返回：
        优化后的依赖图（新对象，不影响输入）。
    """
    optimized: Dict[str, List[DependencyEdge]] = defaultdict(list)

    for source, edges in graph.items():
        for edge in edges:
            new_edge = DependencyEdge(
                source_file=edge.source_file,
                target_file=edge.target_file,
                dep_types=list(edge.dep_types),
                weight=edge.weight,
                symbols=list(edge.symbols),
                is_cycle=edge.is_cycle,
            )

            # 权重调整
            if 'type' in edge.dep_types and len(edge.dep_types) == 1:
                new_edge.weight *= 0.3

            if 'data_flow' in edge.dep_types:
                new_edge.weight *= 1.5

            if edge.is_cycle:
                # 循环依赖边提权：确保 LLM 注意到此高风险边
                new_edge.weight += 0.2

            # 归一化到 [0.1, 2.0]
            new_edge.weight = max(0.1, min(2.0, new_edge.weight))

            optimized[source].append(new_edge)

    return dict(optimized)


# ============================================================================
# P1 函数：跨文件上下文提取 (BFS)
# ============================================================================

def get_cross_file_context(
    target_file: str,
    graph: Dict[str, List[DependencyEdge]],
    max_depth: int = 2,
    max_files: int = 5,
) -> Dict:
    """
    根据依赖图，通过 BFS 提取跨文件上下文。

    参数：
        target_file: 目标文件的绝对路径。
        graph: 依赖图（build_dependency_graph 的输出）。
        max_depth: BFS 最大深度（默认 2）。
        max_files: 每层返回的最大文件数（默认 5，防止上下文溢出）。

    返回：
        {
            'target_file': '...',
            'dependencies': {
                'depth_1': [
                    {
                        'file': '...',
                        'types': ['component'],
                        'weight': 1.5,
                        'symbols': ['MyComponent'],
                        'is_cycle': False,
                        'via': ['IntermediateFile.ets']  # 仅 depth ≥ 2
                    }, ...
                ],
                'depth_2': [...]
            },
            'cyclical_dependencies': [['FileA.ets', 'FileB.ets', 'FileA.ets'], ...],
            'total_dependencies': N
        }
    """
    result: Dict = {
        'target_file': target_file,
        'dependencies': {},
        'cyclical_dependencies': [],
        'total_dependencies': 0,
    }

    # path 记录从 root 到当前节点（含）的完整文件路径序列
    # 初始时仅包含 root
    visited: Set[str] = {target_file}
    queue: deque = deque([(target_file, 0, [target_file])])
    depth_results: Dict[int, List[Dict]] = defaultdict(list)

    while queue:
        current, depth, path = queue.popleft()

        if depth >= max_depth:
            continue

        if current not in graph:
            continue

        for edge in graph[current]:
            target = edge.target_file

            # 检测循环依赖链
            if target in visited:
                if target in path:
                    cycle = path[path.index(target):] + [target]
                    if cycle not in result['cyclical_dependencies']:
                        result['cyclical_dependencies'].append(cycle)
                continue

            visited.add(target)

            dep_info: Dict = {
                'file': target,
                'types': edge.dep_types,
                'weight': edge.weight,
                'symbols': edge.symbols,
                'is_cycle': edge.is_cycle,
            }
            # via 排除 root 自身，只显示中间节点
            intermediates = path[1:]
            if intermediates:
                dep_info['via'] = [os.path.basename(p) for p in intermediates]

            depth_results[depth + 1].append(dep_info)
            queue.append((target, depth + 1, path + [target]))

    # 按权重排序，限制每层文件数
    for d in range(1, max_depth + 1):
        deps = sorted(
            depth_results[d],
            key=lambda x: x['weight'],
            reverse=True,
        )
        result['dependencies'][f'depth_{d}'] = deps[:max_files]
        result['total_dependencies'] += len(deps[:max_files])

    return result


# ============================================================================
# P2 函数：数据流增强（可选）
# ============================================================================

def _find_component_definition(
    component_name: str,
    graph: Dict[str, List[DependencyEdge]],
    current_file: str,
) -> Optional[str]:
    """
    在依赖图中查找组件的定义文件。

    参数：
        component_name: 组件名（如 'MyComponent'）。
        graph: 依赖图。
        current_file: 当前文件路径。

    返回：
        组件定义文件的绝对路径，或 None。
    """
    # 在当前文件的直接依赖中查找
    for edge in graph.get(current_file, []):
        if component_name in edge.symbols:
            return edge.target_file
    return None


def enrich_with_dataflow(
    graph: Dict[str, List[DependencyEdge]],
    all_files: List[str],
    project_root: str,
) -> Dict[str, List[DependencyEdge]]:
    """
    推断 @State/@Prop/@Link 变量传递的数据流依赖（简化版）。

    仅分析直接的父子组件传递关系：
        - 如果 FileA 中使用了 <ChildComponent count={this.count}>
        - 且 ChildComponent 在 FileB 中定义，且 FileB 有 @Prop count
        - 则在 FileA → FileB 之间增加 data_flow 类型的边

    参数：
        graph: 现有的依赖图。
        all_files: 所有文件路径列表。
        project_root: 项目根目录。

    返回：
        增强后的依赖图（新对象，不影响输入）。
    """
    import copy

    enriched: Dict[str, List[DependencyEdge]] = defaultdict(list)
    for src, edges in graph.items():
        enriched[src] = [copy.deepcopy(e) for e in edges]

    # 匹配组件使用模式：<ComponentName attr1={this.xxx} attr2={...}>
    component_usage_re = re.compile(
        r"<(\w+)\s+[^>]*?(?:\/>|>[\s\S]*?<\/\1>)",
        re.MULTILINE,
    )

    # 匹配属性传递：attrName={this.stateVar}
    prop_binding_re = re.compile(
        r"(\w+)=\{this\.(\w+)\}",
        re.MULTILINE,
    )

    for file_path in all_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
        except Exception:
            continue

        for comp_match in component_usage_re.finditer(source):
            component_name = comp_match.group(1)
            usage_text = comp_match.group(0)

            # 查找传入的属性
            props: List[Tuple[str, str]] = prop_binding_re.findall(usage_text)

            if not props:
                continue

            # 查找组件定义文件
            target_file = _find_component_definition(
                component_name, enriched, file_path,
            )
            if target_file:
                for prop_name, _state_var in props:
                    edge = DependencyEdge(
                        source_file=file_path,
                        target_file=target_file,
                        dep_types=['data_flow'],
                        weight=1.0,
                        symbols=[prop_name],
                    )
                    enriched[file_path].append(edge)

    return dict(enriched)


# ============================================================================
# 工厂函数：创建跨文件上下文提取器
# ============================================================================

def create_cross_file_extractor(project_root: str):
    """
    工厂函数：一键创建跨文件上下文提取器。

    用法：
        extractor = create_cross_file_extractor('/path/to/project')
        summary = extractor.get_graph_summary()
        cross_context = extractor.get_context('path/to/file.ets')

    返回：
        CrossFileContextExtractor 实例。
    """
    all_files = scan_project_files(project_root)
    raw_graph = build_dependency_graph(all_files, project_root)
    optimized_graph = optimize_dependency_graph(raw_graph)

    class CrossFileContextExtractor:
        """跨文件上下文提取器（工厂返回的实例）。"""

        def __init__(self, graph, proj_root):
            self.graph = graph
            self.project_root = proj_root

        def get_context(
            self,
            file_path: str,
            max_depth: int = 2,
            max_files: int = 5,
        ) -> Dict:
            """提取跨文件上下文。"""
            return get_cross_file_context(
                file_path, self.graph, max_depth, max_files,
            )

        def get_graph_summary(self) -> Dict:
            """返回依赖图的摘要统计。"""
            total_nodes = len(self.graph)
            total_edges = sum(len(edges) for edges in self.graph.values())
            cycle_edges = sum(
                1 for edges in self.graph.values()
                for e in edges if e.is_cycle
            )
            return {
                'total_files': total_nodes,
                'total_dependencies': total_edges,
                'cycle_edges': cycle_edges,
                'avg_depth': total_edges / max(total_nodes, 1),
            }

    return CrossFileContextExtractor(optimized_graph, project_root)


# ============================================================================
# Prompt 集成辅助函数
# ============================================================================

def build_cross_file_section(cross_context: Dict) -> str:
    """
    将跨文件依赖信息格式化为 LLM Prompt 文本。

    控制长度以防止上下文窗口溢出：每层最多 5 个文件，每个文件一行。

    参数：
        cross_context: get_cross_file_context() 的返回值。

    返回：
        可直接追加到 Prompt 中的 Markdown 格式文本。
    """
    if not cross_context or cross_context.get('total_dependencies', 0) == 0:
        return ''

    section = '### 跨文件依赖关系\n\n'
    section += (
        f"当前修复的文件 `{os.path.basename(cross_context['target_file'])}` "
        f"存在以下跨文件依赖：\n\n"
    )

    for depth_key in sorted(cross_context.get('dependencies', {}).keys()):
        deps = cross_context['dependencies'][depth_key]
        if not deps:
            continue

        depth_num = depth_key.split('_')[1]
        section += f"**直接依赖（深度 {depth_num}）：**\n"

        for dep in deps[:5]:
            dep_types_str = '、'.join(dep.get('types', ['unknown']))
            weight = dep.get('weight', 1.0)

            section += f"- `{os.path.basename(dep['file'])}` "
            section += f"（依赖类型: {dep_types_str}，权重: {weight:.1f}）"

            if dep.get('symbols'):
                section += f" → 导入了 `{', '.join(dep['symbols'][:3])}`"

            if dep.get('is_cycle'):
                section += ' ⚠️ **循环依赖风险**'

            if dep.get('via'):
                section += f"（经由: `{' → '.join(dep['via'])}`）"

            section += '\n'

        section += '\n'

    # 循环依赖警告
    cycles = cross_context.get('cyclical_dependencies', [])
    if cycles:
        section += (
            '**⚠️ 关键警告 — 循环依赖检测：** '
            '以下文件形成循环依赖链。在 ArkTS (ESM) 中，循环依赖可能破坏模块初始化顺序，'
            '导致运行时 `ReferenceError`（被引用的变量/函数尚未初始化即被调用）。'
            '修复当前文件时，请务必避免：\n'
            '1. 在循环依赖的两端文件中同时修改互相引用的导出符号\n'
            '2. 在初始化阶段（顶层代码）调用来自循环依赖链上模块的函数\n'
            '3. 建议优先考虑将共享逻辑提取到独立模块中以打破循环\n\n'
        )
        for cycle in cycles[:3]:
            cycle_path = ' → '.join(os.path.basename(f) for f in cycle)
            section += f"- `{cycle_path}`\n"
        section += '\n'

    section += (
        '**修复建议：** '
        '修改当前文件时，请注意被依赖文件中的相关定义。'
        '如果当前文件被其他文件依赖，请确保修改后的接口保持兼容。\n'
    )

    return section


# ============================================================================
# CLI 入口（用于手动测试）
# ============================================================================

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python cross_file_dependency.py <project_root>")
        print("       python cross_file_dependency.py <project_root> --verbose")
        print("       python cross_file_dependency.py <project_root> --graph [file.ets]")
        sys.exit(1)

    root = sys.argv[1]
    verbose = '--verbose' in sys.argv
    graph_mode = '--graph' in sys.argv

    print(f"=== Cross-File Dependency Analysis ===")
    print(f"Project root: {root}")
    print()

    # 运行自检
    report = self_test(root)
    print(f"Total .ets/.ts files found: {report['total_files']}")
    print(f"Files with imports:        {report['files_with_imports']}")
    print(f"Files with exports:        {report['files_with_exports']}")
    print(f"Files with decorators:     {report['files_with_decorators']}")
    print(f"Total imports:             {report['total_imports']}")
    print(f"Total exports:             {report['total_exports']}")

    if report['errors']:
        print(f"\nErrors ({len(report['errors'])}):")
        for err in report['errors']:
            print(f"  - {err}")

    # 图模式：构建依赖图并展示
    if graph_mode:
        print(f"\n{'='*60}")
        print("Dependency Graph")
        print(f"{'='*60}")

        all_files = scan_project_files(root)
        graph = build_dependency_graph(all_files, root)

        # 摘要
        extractor_obj = create_cross_file_extractor(root)
        summary = extractor_obj.get_graph_summary()
        print(f"Total nodes:        {summary['total_files']}")
        print(f"Total edges:        {summary['total_dependencies']}")
        print(f"Cycle edges:        {summary['cycle_edges']}")
        print(f"Avg out-degree:     {summary['avg_depth']:.2f}")

        # 循环边详情
        cycle_edges = []
        for src, edges in graph.items():
            for e in edges:
                if e.is_cycle:
                    cycle_edges.append((src, e))
        if cycle_edges:
            print(f"\n⚠️  Cycle edges ({len(cycle_edges)}):")
            for src, e in cycle_edges:
                print(f"  {os.path.basename(src)} → {os.path.basename(e.target_file)} ({', '.join(e.dep_types)})")

        # 如果有指定文件，展示其 BFS 上下文
        target_arg = None
        for i, arg in enumerate(sys.argv):
            if arg == '--graph' and i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith('--'):
                target_arg = sys.argv[i + 1]
                break

        if target_arg:
            # 匹配文件名
            target_file = None
            for f in all_files:
                if target_arg in f:
                    target_file = f
                    break

            if target_file:
                print(f"\n{'='*60}")
                print(f"BFS Context for: {os.path.relpath(target_file, root)}")
                print(f"{'='*60}")
                ctx = get_cross_file_context(target_file, graph, max_depth=2, max_files=5)
                print(f"Total dependencies: {ctx['total_dependencies']}")

                for depth_key in sorted(ctx.get('dependencies', {}).keys()):
                    deps = ctx['dependencies'][depth_key]
                    if deps:
                        print(f"\n  {depth_key}:")
                        for d in deps:
                            cycle_marker = ' ⚠️ CYCLE' if d.get('is_cycle') else ''
                            via = f" (via: {' → '.join(d.get('via', []))})" if d.get('via') else ''
                            print(f"    - {os.path.basename(d['file'])} [{', '.join(d['types'])}] w={d['weight']:.1f}{cycle_marker}{via}")

                if ctx['cyclical_dependencies']:
                    print(f"\n  ⚠️ Cyclical chains:")
                    for cycle in ctx['cyclical_dependencies']:
                        print(f"    {' → '.join(os.path.basename(f) for f in cycle)}")
            else:
                print(f"\nFile matching '{target_arg}' not found in project.")

        # 每文件出边摘要
        if verbose:
            print(f"\n{'='*60}")
            print("Per-file outgoing edges:")
            print(f"{'='*60}")
            for src, edges in sorted(graph.items()):
                if edges:
                    rel = os.path.relpath(src, root)
                    print(f"\n  {rel} →")
                    for e in sorted(edges, key=lambda x: x.weight, reverse=True):
                        cycle_marker = ' ⚠️ CYCLE' if e.is_cycle else ''
                        print(f"    → {os.path.basename(e.target_file)} [{', '.join(e.dep_types)}] w={e.weight:.1f}{cycle_marker}")

    # 详细模式：打印每个文件的分析结果
    elif verbose:
        print(f"\n{'='*60}")
        print("Per-file analysis:")
        print(f"{'='*60}")

        files = scan_project_files(root)
        for fpath in files:
            analysis = analyze_single_file(fpath)
            rel = os.path.relpath(fpath, root)
            print(f"\n--- {rel} ---")

            if analysis.imports:
                print("  Imports:")
                for imp in analysis.imports:
                    print(f"    [{imp['import_type']}] {imp['symbols']} from '{imp['module']}' (line {imp['line']})")

            if analysis.exports:
                print("  Exports:")
                for exp in analysis.exports:
                    extra = f" (from '{exp['module']}')" if exp.get('module') else ''
                    print(f"    [{exp['type']}] {exp['name']}{extra} (line {exp['line']})")

            if analysis.decorators:
                print("  Decorators:")
                for target, decos in analysis.decorators.items():
                    print(f"    {target}: {', '.join(decos)}")

            if analysis.state_variables:
                print(f"  @State vars: {analysis.state_variables}")

    print(f"\nDone.")

from llm import get_deepseek_answer
import sys
import os

SYSTEM_PROMPT = """You are an expert ArkTS code repair assistant. Fix performance and security defects in OpenHarmony ArkTS code.

Output ONLY the fixed code in a code block."""

def extract_code(response):
    if not response:
        return ""
    code = response.strip()
    if "```" in code:
        code = code.split("```")[1]
        if '\n' in code:
            code = code[code.index('\n')+1:]
    return code.strip()

def repair_code(code):
    prompt = f"Fix any defects in this ArkTS code:\n```\n{code}\n```"
    resp = get_deepseek_answer(prompt, model_name="deepseek-chat", system_prompt=SYSTEM_PROMPT)
    return extract_code(resp)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        with open(input_path, 'r', encoding='utf-8') as f:
            code = f.read()
    else:
        input_path = None
        code = '''@Entry
@Component
struct Index {
  build() {
    Column() {
      Text('Hello')
    }
  }
}'''

    print("Repairing...")
    result = repair_code(code)

    if input_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_fixed{ext}"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"Original: {input_path}")
        print(f"Fixed:    {output_path}")
    else:
        print(result)

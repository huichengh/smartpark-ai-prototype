"""模拟 OpenAI 兼容端点，用于验证 llm_client 的工具调用链路。

真实环境换成 Qwen（Ollama / DashScope）即可，协议一致：
第一次请求返回 tool_call，第二次（收到 role=tool 后）返回八段式 JSON。
数字从工具结果里抄，用来验证"数字由工具产生、模型只负责组织"。
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

TOOL_NAME = "get_dashboard_summary"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静音
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []

        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            # 第一轮：让模型"决定"调一个工具
            payload = {
                "id": "mock-1", "object": "chat.completion",
                "choices": [{
                    "index": 0, "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant", "content": None,
                        "tool_calls": [{
                            "id": "call_1", "type": "function",
                            "function": {"name": TOOL_NAME, "arguments": "{}"},
                        }],
                    },
                }],
            }
        else:
            # 第二轮：从工具结果里挑一个真实数字，写进结论
            raw = tool_msgs[-1].get("content") or "{}"
            rate = None
            # 工具返回形如 {"data": {"kpis": [{"key": "occupancy_rate", ..., "value": 82.35}]}}
            m = re.search(r'"occupancy_rate"[\s\S]{0,200}?"value"\s*:\s*([0-9.]+)', raw)
            if m:
                rate = m.group(1)
            conclusion = (f"当前园区出租率 {rate}%。" if rate
                          else "工具已返回经营数据，详见关键数据。")
            content = json.dumps({
                "结论": conclusion,
                "关键数据": ([{"label": "出租率", "value": rate, "unit": "%"}]
                             if rate else []),
                "原因分析": ["数据来自平台经营指标接口"],
                "建议措施": ["关注空置空间的招商方案"],
                "影响范围": "全园区",
                "风险": ["空置面积较大时现金流承压"],
                "责任部门/角色": ["招商主管"],
                "决策状态": "INFO",
            }, ensure_ascii=False)
            payload = {
                "id": "mock-2", "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
            }

        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8899), Handler).serve_forever()

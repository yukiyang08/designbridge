# DesignBridge – LangGraph Multi-Agent Specification (簡化版的需求文件)

## 1. System Goal
DesignBridge aims to generate interior design images through a **multi-agent, iterative workflow**.
The system decomposes the design process into specialized agents coordinated by a central controller.
LangGraph is used to manage **stateful workflow execution, routing, and iteration control**.

---

## 2. Global Workflow Overview

User Input  
→ Requirement Analysis  
→ Visual Preprocessing  
→ 路由（由 Requirement Analysis 決定：新設計或局部修改）  
→ (Layout agent / Style agent / Adjuster agent / Layout+Style 協作)  
→ Rendering  
→ Evaluation  
→ (Stop or Iterate)

**路由**由 Requirement Analyzer 負責：依據 **Requirement Analysis 輸出的 JSON** 與 **Visual Preprocessing 後的結果**，決定要將任務交給 **Layout agent**、**Style agent**、**Adjuster agent**，或是讓 **Layout + Style agent 協作**。工作流支援條件路由與多輪迭代。

---

## 3. Shared State Definition (LangGraph State)

The global state is shared across agents.

```json
{
  "task_id": "string",
  "iteration": "int",

  "user_input": {
    "initial_image": "image_path_or_id",
    "text_prompt": "string",
    "edit_scope": "float (0~1)"
  },

  "structured_requirement": "json_object",
  "vision_features": {
    "segmentation": "path_or_tensor",
    "depth": "path_or_tensor",
    "geometry_constraints": "json_object"
  },

  "routing_decision": "enum",
  "intermediate_outputs": {},

  "generated_image": "image_path_or_id",
  "evaluation_result": {
    "scores": "json_object",
    "decision": "continue | stop",
    "feedback": "string"
  }
}

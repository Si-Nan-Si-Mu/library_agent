from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

# 引入刚才写的两个自定义模块
from actions.neo4j_connector import get_books_by_topic
from actions.llm_server import generate_ollama_reply

class ActionRecommendByTopic(Action):

    def name(self) -> Text:
        # 这个名字必须和 domain.yml 中 actions 列表下的名字一模一样
        return "action_recommend_by_topic"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # 1. 从对话上下文中获取 Rasa NLU 提取到的 topic 实体
        topic = tracker.get_slot("topic")
        
        # 兜底逻辑：如果没有识别到 topic
        if not topic:
            dispatcher.utter_message(text="抱歉，我没有听清你想看哪个研究方向的书，能具体说说吗？例如：'我想看人工智能方向的。'")
            return []

        # 给用户一个正在处理的反馈
        dispatcher.utter_message(text=f"好的，正在知识图谱中为您检索【{topic}】方向的藏书，请稍候...")

        # 2. 调用 Neo4j 图谱查询数据
        kg_results = get_books_by_topic(topic)

        # 3. 兜底逻辑：如果图谱里查不到这个方向的书
        if not kg_results:
            dispatcher.utter_message(text=f"很遗憾，我们馆内目前还没有关于【{topic}】方向的专门藏书，要不换个方向试试？")
            return []

        # 4. 如果查到了数据，交给 Ollama 生成自然语言回复
        print(f"--- 准备提交给 LLM 的数据: {kg_results} ---") 
        reply = generate_ollama_reply(topic, kg_results)

        # 5. 把大模型生成的最终回复发给用户
        dispatcher.utter_message(text=reply)

        return [SlotSet("topic", None)]  # 用完就丢，清空这个槽位，准备下一轮对话
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, AllSlotsReset, ActiveLoop
from rasa_sdk.forms import FormValidationAction


### -------------- 挂号意图 ----------------------

class ValidateRegisterForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_register_form"

class ActionRegisterFormSubmit(Action):
    def name(self) -> Text:
        return "action_register_form_submit"

    def run(self, dispatcher, tracker, domain):
        # 表单填完后统一提示确认
        dispatcher.utter_message(
            response="utter_ask_register_confirm", **tracker.slots
        )

        return []


class ActionRegister(Action):
    def name(self) -> Text:
        return "action_register"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        api_succeed = tracker.get_slot("person_doctor") == "李医生"

        return [AllSlotsReset(), SlotSet("api_register_succeed", api_succeed), ActiveLoop(None)]


### -------------- 查询排班意图 ----------------------

class ValidateQueryDoctorForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_query_doctor_form"

class ActionQueryDoctorFormSubmit(Action):
    def name(self) -> Text:
        return "action_query_doctor_form_submit"

    def run(self, dispatcher, tracker, domain):
        # 表单填完后统一提示确认
        dispatcher.utter_message(
            response="utter_ask_query_doctor_confirm", **tracker.slots
        )
        return []


class ActionQueryDoctor(Action):
    def name(self) -> Text:
        return "action_query_doctor"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        doctor = tracker.get_slot("person_doctor")
        department = tracker.get_slot("department")
        date = tracker.get_slot("date")
        api_succeed = (doctor == "李医生" and department == "内科" and date == "本周")

        return [AllSlotsReset(), SlotSet("api_query_doctor_succeed", api_succeed), ActiveLoop(None)]


### -------------- 缴费意图 ----------------------

class ValidatePayForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_pay_form"

class ActionPayFormSubmit(Action):
    def name(self) -> Text:
        return "action_pay_form_submit"

    def run(self, dispatcher, tracker, domain):
        # 表单填完后统一提示确认
        dispatcher.utter_message(
            response="utter_ask_pay_confirm", **tracker.slots
        )
        return []


class ActionPay(Action):
    def name(self) -> Text:
        return "action_pay"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        api_succeed = tracker.get_slot("payment") == "支付宝"       
        
        return [AllSlotsReset(), SlotSet("api_pay_succeed", api_succeed), ActiveLoop(None)]



### -------------- 查询症状意图 ----------------------

class ValidateQuerysymptomForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_query_symptom_form"

class ActionQuerysymptomFormSubmit(Action):
    def name(self) -> Text:
        return "action_query_symptom_form_submit"

    def run(self, dispatcher, tracker, domain):
        # 表单填完后统一提示确认
        dispatcher.utter_message(
            response="utter_ask_query_symptom_confirm", **tracker.slots
        )
        return []


class ActionQuerysymptom(Action):
    def name(self) -> Text:
        return "action_query_symptom"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        symptom = tracker.get_slot("symptom")
        api_succeed = symptom == "咳嗽"
        
        return [AllSlotsReset(), SlotSet("api_query_symptom_succeed", api_succeed), ActiveLoop(None)]


"""
評分 prompt（judge prompt）

【來源】
以下五個模板「逐字複製」自 LongMemEval 官方程式：
    third_party/LongMemEval/src/evaluation/evaluate_qa.py 的 get_anscheck_prompt()
    官方 repo：https://github.com/xiaowu0162/LongMemEval
    下載時的 commit：9e0b455f4ef0e2ab8f2e582289761153549043fc
    授權：MIT License（Copyright (c) 2024 Di Wu）

對應論文：p.20 附錄 A.4 的 Figure 10（各題型的評分規則）。
注意：論文 Figure 10 沒有列出「拒答題（abstention）」的模板，
      拒答題的模板只出現在官方程式中，所以這裡以官方程式為準。

【為什麼不自己改寫】
模板文字只要改一個字，judge 的判斷就可能不同，
數字就無法再跟論文或其他研究比較。所以這個檔案「只能複製、不能修改」。
如果真的要改，請在 EVAL_NOTES.md 的修改紀錄中寫明原因。
"""

# ---------------------------------------------------------------------------
# 一、記錄 prompt 的來源版本
# ---------------------------------------------------------------------------
# 這個字串會被寫進每一筆評分結果，日後可以追查「這筆分數是用哪個版本的 prompt 評的」。
PROMPT_SOURCE = "LongMemEval@9e0b455f4ef0e2ab8f2e582289761153549043fc"


# ---------------------------------------------------------------------------
# 二、五個模板（逐字複製，請勿修改）
# ---------------------------------------------------------------------------
# Python 語法說明：
#   - 用三個雙引號 """ 或一般引號包起來的是「字串」。
#   - 字串裡的 {} 是「佔位符」，之後用 .format(a, b, c) 依序填入問題、答案、回答。
#   - \n 代表換行。
#   - 括號內相鄰的多段字串，Python 會自動接成一個字串（這樣寫只是為了方便閱讀）。

# 一般題型：single-session-user、single-session-assistant、multi-session
TEMPLATE_DEFAULT = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response is equivalent to the correct answer or contains all the intermediate steps "
    "to get the correct answer, you should also answer yes. If the response only contains a subset "
    "of the information required by the answer, answer no. "
    "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)

# 時間推理題：多了「天數差 1 不扣分」的規則
TEMPLATE_TEMPORAL = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response is equivalent to the correct answer or contains all the intermediate steps "
    "to get the correct answer, you should also answer yes. If the response only contains a subset "
    "of the information required by the answer, answer no. In addition, do not penalize off-by-one "
    "errors for the number of days. If the question asks for the number of days/weeks/months, etc., "
    "and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), "
    "the model's response is still correct. "
    "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)

# 知識更新題：同時提到舊資訊沒關係，只要更新後的答案正確
TEMPLATE_KNOWLEDGE_UPDATE = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response contains some previous information along with an updated answer, "
    "the response should be considered as correct as long as the updated answer is the required answer."
    "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)

# 偏好題：沒有標準答案，第二個欄位放的是評分準則（Rubric）
TEMPLATE_PREFERENCE = (
    "I will give you a question, a rubric for desired personalized response, and a response from a model. "
    "Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
    "The model does not need to reflect all the points in the rubric. The response is correct "
    "as long as it recalls and utilizes the user's personal information correctly."
    "\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)

# 拒答題：question_id 以 "_abs" 結尾的題目；第二個欄位是「為什麼無法回答」的說明
TEMPLATE_ABSTENTION = (
    "I will give you an unanswerable question, an explanation, and a response from a model. "
    "Please answer yes if the model correctly identifies the question as unanswerable. "
    "The model could say that the information is incomplete, or some other information is given "
    "but the asked information is not."
    "\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\n"
    "Does the model correctly identify the question as unanswerable? Answer yes or no only."
)


# ---------------------------------------------------------------------------
# 三、依題型挑模板
# ---------------------------------------------------------------------------
# dict（字典）：用「鍵 → 值」的方式查表。這裡的鍵是題型名稱，值是對應的模板。
TEMPLATE_BY_TYPE = {
    "single-session-user": TEMPLATE_DEFAULT,
    "single-session-assistant": TEMPLATE_DEFAULT,
    "multi-session": TEMPLATE_DEFAULT,
    "temporal-reasoning": TEMPLATE_TEMPORAL,
    "knowledge-update": TEMPLATE_KNOWLEDGE_UPDATE,
    "single-session-preference": TEMPLATE_PREFERENCE,
}


def build_judge_prompt(question_type, question, answer, response, is_abstention):
    """
    組出要送給 judge 的完整 prompt。

    參數：
        question_type : 題型，例如 "temporal-reasoning"
        question      : 問題原文
        answer        : 參考答案（偏好題是 rubric；拒答題是說明）
        response      : 要被評分的模型回答（已經過答案提取）
        is_abstention : 是否為拒答題（True / False）

    回傳：
        一個字串，就是完整的 prompt。

    邏輯與官方 get_anscheck_prompt() 相同：
        拒答題 → 一律用拒答模板（不管原本的題型）
        其他   → 依題型查表
    """
    if is_abstention:
        template = TEMPLATE_ABSTENTION
    else:
        # 查不到題型時，官方程式會直接報錯（NotImplementedError）。
        # 這裡改成給出比較清楚的錯誤訊息，行為一樣是停止。
        if question_type not in TEMPLATE_BY_TYPE:
            raise ValueError(f"未知的題型：{question_type}")
        template = TEMPLATE_BY_TYPE[question_type]

    # 依序把 問題、答案、回答 填進三個 {} 佔位符。
    # 官方資料中有 32 題的答案是整數（例如 3），用 str() 轉成字串比較保險。
    return template.format(question, str(answer), response)

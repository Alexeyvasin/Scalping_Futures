# # Please install OpenAI SDK first: `pip3 install openai`
#
# from openai import OpenAI
#
# client = OpenAI(api_key="sk-d30c72a9ce994731bcc1d69b4684b1f4", base_url="https://api.deepseek.com")
#
# response = client.chat.completions.create(
#     model="deepseek-chat",
#     messages=[
#         {"role": "system", "content": "Hi! Tell me some joke please."},
#         {"role": "user", "content": "Hello"},
#     ],
#     stream=False
# )
#
# print(response.choices[0].message.content)

#AIzaSyBaiCGjigrTRUSq_Fa8onfhCsa5xECP6G8

from google import genai

client = genai.Client(api_key="AIzaSyBaiCGjigrTRUSq_Fa8onfhCsa5xECP6G8")

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Explain how AI works",
)

print(response.text)
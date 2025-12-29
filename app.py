import google.generativeai as genai
import os

# 請將下方引號內的文字換成您的 API Key
os.environ["GOOGLE_API_KEY"] = "AIzaSyBEGnLEHKvqsH93ltM6jDmuppPLH3cbuS0"
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

print("您目前可用的模型清單：")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)

import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("LEADRAT_API_KEY")
api_secret = os.getenv("LEADRAT_API_SECRET")

url = "https://connect.leadrat.com/api/v1/authentication/token"

headers = {
    "tenant": "valuepersqft"
}

body = {
    "apiKey": api_key,
    "secretKey": api_secret
}

response = requests.post(url, headers=headers, json=body)

print("Status code:", response.status_code)
print("Response:", response.json())
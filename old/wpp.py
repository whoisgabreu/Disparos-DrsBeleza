import requests as rq

BASE_URL = "evolution.v4lisboatech.com.br"

ACTION_TYPE = "/message"
ACTION = "/sendText"

INSTANCE_NAME = "/Gabriel Lucas - DEV"

API_KEY = "6E30DF765BBA-43B5-8986-696F99E3AD6A"

def sendText(number: str):

	header = {
		"Content-Type": "application/json",
		"apikey": API_KEY
	}

	payload = {
		"number": number,
		"text": f"http://192.168.3.33:8000/reativar/{number}",
		"delay": 5000,
		"linkPreview": True
	}

	print(f"https://{BASE_URL}{ACTION_TYPE}{ACTION}{INSTANCE_NAME}")

	response = rq.post(url = f"https://{BASE_URL}{ACTION_TYPE}{ACTION}{INSTANCE_NAME}", headers = header, json = payload)

	return (response.status_code, response.json())
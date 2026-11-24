from wpp import sendText
import json


with open("reativar.json", "r") as lista:
    teste = json.load(lista)


for i in teste.values():
    # print(i["number"])
    sendText(i["number"])

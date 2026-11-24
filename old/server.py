from flask import Flask, redirect

app = Flask(__name__)

@app.route("/reativar/<string:slug>")
def action(slug):
    # Aqui você pode salvar ou processar o slug antes de redirecionar
    print(f"Redirecionando a partir do slug: {slug}")
    
    return redirect("https://wa.me/5531991519947?text=Olá%2C+vim+do+Google+e+quero+agendar+meu+momento+de+SPA+na+Drs+da+Beleza.+(cód.+ZAS193UB)")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
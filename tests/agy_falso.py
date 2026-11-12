"""agy falso para os testes: o comportamento sai do nome do modelo.

  modelo-ok / outros -> responde "RESPOSTA <modelo> PROMPT=<prompt>"
  *jetski*           -> "jetski: no output produced ..." e JSON com resposta vazia
  *vazio*            -> JSON com resposta vazia
  *telemetria*       -> erro do plugin de telemetria no stderr, sem JSON
  *citacao*          -> resposta longa e valida que CITA "unknown model" e "datacloud_telemetry"
  *edita*            -> altera calc.py e cria novo.txt no cwd (para o patch do delegar)
  *lento*            -> dorme 60 s
  *updater-<s>*      -> responde, deixando um neto destacado com cwd na copia por <s> segundos
  *neto*             -> abre um neto que herda o stdout e dorme 60 s, e dorme tambem
  `agy models`       -> lista de FAKE_MODELOS (separados por virgula)
Registra em FAKE_REGISTRO: modelo|cwd|modo|USERPROFILE|tem-settings|arquivos-no-diff (-1: sem diff)
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
args = sys.argv[1:]
if args[:1] == ["models"]:
    print("Fetching available models...")
    for m in os.environ.get("FAKE_MODELOS", "").split(","):
        if m:
            print(f"{m}\t{m}")
    sys.exit(0)

modelo = args[args.index("--model") + 1]
prompt = args[args.index("-p") + 1]
perfil = os.environ.get("USERPROFILE", "")
settings = Path(perfil) / ".gemini" / "antigravity-cli" / "settings.json"
with open(os.environ["FAKE_REGISTRO"], "a", encoding="utf-8") as f:
    diff = Path("ARGON_DIFF.patch")
    f.write(f"{modelo}|{os.getcwd()}|{args[args.index('--mode') + 1]}|{perfil}|{settings.is_file()}"
            f"|{diff.read_text(encoding='utf-8').count('+++') if diff.exists() else -1}\n")


def responder(texto, **extra):
    print(json.dumps({"conversation_id": "falso", "status": "SUCCESS", "response": texto,
                      "usage": {"input_tokens": 100, "output_tokens": 10}, **extra}, ensure_ascii=False))


if "jetski" in modelo:
    print('jetski: no output produced — a tool required the "read_file" permission ...')
    responder("")
elif "vazio" in modelo:
    responder("")
elif "telemetria" in modelo:
    print("Error: Cannot find module 'C:\\x\\datacloud_telemetry\\telemetry_hook_bundle.js'", file=sys.stderr)
elif "citacao" in modelo:
    responder("Revisao da ponte. " + "texto " * 300
              + "\nA funcao classificar trata 'unknown model' e o plugin datacloud_telemetry.")
elif "edita" in modelo:
    Path("calc.py").write_text("def soma(a, b):\n    return a + b\n", encoding="utf-8")
    Path("novo.txt").write_text("criado\n", encoding="utf-8")
    responder("editei")
elif "lento" in modelo:
    time.sleep(60)
elif "updater" in modelo:
    # Imita o `agy --bg-updater`: neto destacado, com o cwd na copia, que sobrevive ao pai.
    segundos = modelo.rsplit("-", 1)[-1]
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    marca = Path("updater-vivo")
    subprocess.Popen([sys.executable, "-c",
                      f"import time, pathlib; pathlib.Path('{marca}').touch(); time.sleep({segundos})"],
                     cwd=os.getcwd(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")
    prazo = time.monotonic() + 10  # so responde com o neto de pe, senao o teste corre contra a partida
    while not marca.exists() and time.monotonic() < prazo:
        time.sleep(0.05)
    responder("ok com updater")
elif "neto" in modelo:
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(60)
else:
    extra = {"structured_output": {"ok": True}} if "--json-schema" in args else {}
    responder(f"RESPOSTA {modelo} PROMPT={prompt}", **extra)

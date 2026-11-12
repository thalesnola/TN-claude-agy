"""Fase 0: guarda de sigilo e cascata da ponte, com agy falso.

Rodar: python -m unittest discover -s tests -v   (na raiz do repo)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
AUDITOR = next((p for p in (Path(r"C:\ACERVO\Segundo_Cerebro\.sistema\scripts\auditar.py"),
                            Path.home() / "ACERVO/Segundo_Cerebro/.sistema/scripts/auditar.py")
                if p.is_file()), None)
if AUDITOR is None:
    raise unittest.SkipTest("auditor da vault ausente nesta maquina")

TMP = Path(tempfile.mkdtemp(prefix="argon-teste-")).resolve()
CASOS = TMP / "Casos"
TRAB = TMP / "trabalho"
for d in (CASOS / "caso-a", TRAB / "sub"):
    d.mkdir(parents=True)

(TMP / "argon.toml").write_text(
    f"[sigilo]\npastas_caso = [{json.dumps(str(CASOS))}]\nauditor = {json.dumps(str(AUDITOR))}\n",
    encoding="utf-8")
os.environ.update({
    "ARGON_CONFIG": str(TMP / "argon.toml"),
    "ARGON_ESTADO": str(TMP / "estado"),
    "AGY_BIN": str(RAIZ / "tests" / "agy_falso.py"),
    "FAKE_REGISTRO": str(TMP / "chamadas.txt"),
    "ARGON_AREA": str(TMP / "area"),
})
sys.path.insert(0, str(RAIZ / "scripts"))
import area  # noqa: E402
import guarda  # noqa: E402
import ponte  # noqa: E402
AREA = TMP / "area"

# Montado em tempo de execucao para o arquivo de teste nao carregar o identificador inteiro.
CPF_SINTETICO = "123.456.789-" + "09"


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def chamadas():
    p = Path(os.environ["FAKE_REGISTRO"])
    return [l.split("|") for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def criar_atalho(link: Path, alvo: Path) -> bool:
    if os.name == "nt":  # juncao nao exige privilegio, ao contrario do symlink
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(alvo)], capture_output=True)
        return r.returncode == 0
    try:
        os.symlink(alvo, link)
        return True
    except OSError:
        return False


class TestGuarda(unittest.TestCase):
    def setUp(self):
        self.cfg = guarda.carregar_config()

    def bloqueia(self, cwd, arquivos=(), prompt="revise"):
        return guarda.checar(prompt, cwd, list(arquivos), self.cfg)

    def test_casos_padrao_sempre_proibido(self):
        self.assertIsNotNone(self.bloqueia(r"C:\Casos\qualquer"))
        self.assertIsNotNone(self.bloqueia(r"c:\casos"))  # caixa nao importa

    def test_pasta_de_caso_da_config(self):
        self.assertEqual(self.bloqueia(CASOS / "caso-a").motivo, "pasta de caso")

    def test_cwd_ancestral_do_caso_bloqueia(self):
        # cwd = pai de Casos: o agy leria Casos inteira.
        b = self.bloqueia(TMP)
        self.assertIsNotNone(b)
        self.assertIn("contem", " ".join(b.detalhes))

    def test_ancestral_de_pasta_inexistente_passa(self):
        cfg = guarda.Config(pastas_caso=[TRAB / "nao-existe"], auditor=AUDITOR)
        self.assertIsNone(guarda.checar_pastas(TRAB, [], cfg))

    def test_vizinha_com_prefixo_igual_passa(self):
        vizinha = TMP / "Casos-modelos"
        vizinha.mkdir(exist_ok=True)
        self.assertIsNone(self.bloqueia(vizinha))

    def test_codigo_do_acervo_liberado(self):
        self.assertIsNone(guarda.checar_pastas(Path(r"C:\ACERVO\Segundo_Cerebro\.sistema\scripts"), [], self.cfg))

    def test_barras_mistas_e_ponto_ponto(self):
        self.assertIsNotNone(self.bloqueia(str(TRAB) + "/../Casos\\caso-a"))

    @unittest.skipUnless(os.name == "nt", "prefixo \\\\?\\ e UNC sao do Windows")
    def test_prefixo_longo_e_unc(self):
        self.assertIsNotNone(self.bloqueia("\\\\?\\" + str(CASOS / "caso-a")))
        unc = "\\\\localhost\\" + str(CASOS / "caso-a").replace(":", "$", 1)
        self.assertIsNotNone(self.bloqueia(unc))

    def test_atalho_no_cwd_para_caso_bloqueia(self):
        d = TRAB / "com-atalho"
        d.mkdir(exist_ok=True)
        if not criar_atalho(d / "atalho", CASOS / "caso-a"):
            self.skipTest("sem permissao para criar atalho")
        self.assertIsNotNone(self.bloqueia(d))

    def test_cpf_no_prompt_bloqueia_sem_repetir_valor(self):
        b = self.bloqueia(TRAB, prompt=f"confira o titular {CPF_SINTETICO}")
        self.assertIn("identificador", b.motivo)
        self.assertNotIn(CPF_SINTETICO, " ".join(b.detalhes))

    def test_cpf_em_arquivo_citado_bloqueia(self):
        for enc, nome in (("utf-8", "u8.txt"), ("utf-16", "u16bom.txt"), ("utf-16-le", "u16le.txt")):
            with self.subTest(enc=enc):
                (TRAB / nome).write_text(f"titular {CPF_SINTETICO}\n", encoding=enc)
                self.assertIsNotNone(self.bloqueia(TRAB, [TRAB / nome]))

    def test_arquivo_relativo_resolve_contra_o_dir(self):
        # O agy le sub/dados.txt; a ponte roda noutra pasta, onde dados.txt nao existe.
        (TRAB / "sub" / "dados.txt").write_text(f"titular {CPF_SINTETICO}\n", encoding="utf-8")
        self.assertIsNotNone(self.bloqueia(TRAB / "sub", ["dados.txt"]))

    def test_nao_auditavel_bloqueia(self):
        (TRAB / "x.bin").write_bytes(b"\x01\x02\x00\x00\x00\xff\xfe" * 50)
        (TRAB / "x.pdf").write_bytes(b"%PDF-1.7 texto")
        for arq in (TRAB / "x.bin", TRAB / "x.pdf", TRAB / "sub", TRAB / "nao-existe.txt"):
            with self.subTest(arq=arq.name):
                self.assertIsNotNone(self.bloqueia(TRAB, [arq]))

    def test_prompt_tecnico_passa(self):
        self.assertIsNone(self.bloqueia(TRAB, prompt="revise a funcao soma de calc.py, versao 1.4.4"))

    def test_sem_auditor_fecha(self):
        cfg = guarda.Config(pastas_caso=[], auditor=TMP / "nao-existe.py")
        self.assertEqual(guarda.checar_conteudo("oi", [], cfg).motivo, "auditor ausente")

    def test_auditor_quebrado_fecha(self):
        ruim = TMP / "auditor-ruim.py"
        ruim.write_text("def (:\n", encoding="utf-8")
        cfg = guarda.Config(pastas_caso=[], auditor=ruim)
        self.assertEqual(guarda.checar_conteudo("oi", [], cfg).motivo, "auditor com erro")

    def test_config_invalida_fecha(self):
        ruim = TMP / "ruim.toml"
        ruim.write_text("[sigilo\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"ARGON_CONFIG": str(ruim)}):
            self.assertEqual(guarda.checar("oi", TRAB, []).motivo, "configuracao invalida")


class TestPonte(unittest.TestCase):
    def setUp(self):
        Path(os.environ["FAKE_REGISTRO"]).unlink(missing_ok=True)
        ponte.CACHE_MODELOS.unlink(missing_ok=True)
        self.enterContext(mock.patch.dict(ponte.CASCATAS))
        self.enterContext(mock.patch.object(ponte, "FOLGA_TIMEOUT", 2))

    def rodar(self, cascata, papel="explorar", modelos=None, **kw):
        os.environ["FAKE_MODELOS"] = ",".join(modelos if modelos is not None else cascata)
        ponte.CASCATAS[papel] = cascata
        return ponte.executar(papel, kw.pop("prompt", "revise calc.py"), kw.pop("cwd", TRAB),
                              kw.pop("arquivos", []), kw.pop("modelo", None), None, kw.pop("timeout", 30))

    def test_pula_jetski_e_vazio(self):
        cod, r = self.rodar(["modelo-jetski", "modelo-vazio", "modelo-ok"])
        self.assertEqual(cod, 0)
        self.assertEqual([t["estado"] for t in r["tentativas"]], ["negado", "vazio", "ok"])
        self.assertTrue(r["resposta"].startswith("RESPOSTA modelo-ok"))

    def test_pula_modelo_fora_do_catalogo(self):
        cod, r = self.rodar(["modelo-sumiu", "modelo-ok"], modelos=["modelo-ok"])
        self.assertEqual(cod, 0)
        self.assertEqual([c[0] for c in chamadas()], ["modelo-ok"])

    def test_nenhum_modelo_no_catalogo(self):
        self.assertEqual(self.rodar(["modelo-a"], modelos=["outro"])[0], 14)

    def test_todos_negados(self):
        self.assertEqual(self.rodar(["modelo-jetski", "modelo-jetski2"])[0], 15)

    def test_telemetria_para_a_cascata(self):
        cod, r = self.rodar(["modelo-telemetria", "modelo-ok"])
        self.assertEqual(cod, 13)
        self.assertEqual(len(r["tentativas"]), 1)

    def test_resposta_que_cita_erro_continua_ok(self):
        cod, r = self.rodar(["modelo-citacao", "modelo-ok"])
        self.assertEqual(cod, 0)
        self.assertEqual(r["modelo"], "modelo-citacao")

    def test_timeout_pula(self):
        cod, r = self.rodar(["modelo-lento", "modelo-ok"], timeout=1)
        self.assertEqual(r["tentativas"][0]["estado"], "timeout")
        self.assertEqual(cod, 0)

    def test_timeout_mata_arvore_com_neto(self):
        t0 = time.monotonic()
        cod, r = self.rodar(["modelo-neto"], timeout=1)
        self.assertEqual(cod, 12)
        self.assertLess(time.monotonic() - t0, 30)

    def copias_na_area(self):
        # So as copias da ponte (12 hex); outros testes deixam pastas suas na area.
        return ([p for p in AREA.iterdir() if p.is_dir() and re.fullmatch(r"[0-9a-f]{12}", p.name)]
                if AREA.exists() else [])

    def test_updater_vivo_espera_e_apaga(self):
        # Neto com cwd na copia por 2 s: a retentativa espera e a copia some, sem aviso.
        cod, r = self.rodar(["modelo-updater-2"])
        self.assertEqual(cod, 0)
        self.assertNotIn("aviso_limpeza", r)
        self.assertEqual(self.copias_na_area(), [])

    def test_limpeza_presa_vira_aviso_e_varredura_recolhe(self):
        if os.name != "nt":
            self.skipTest("cwd de processo vivo so prende a pasta no Windows")
        with mock.patch.object(area, "ESPERAS", (0.1,)):
            cod, r = self.rodar(["modelo-updater-6"])
        self.assertEqual(cod, 0)  # a sonda nao cai
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["aviso_limpeza"]), 1)
        presa = self.copias_na_area()
        self.assertEqual(len(presa), 1)
        self.assertEqual(list(presa[0].iterdir()), [])  # esvaziada, so a raiz resiste
        # Recem-criada: a varredura poupa (pode ser chamada em curso).
        self.assertEqual(area.varrer_orfas(AREA), [])
        self.assertEqual(len(self.copias_na_area()), 1)
        prazo = time.monotonic() + 20
        while self.copias_na_area() and time.monotonic() < prazo:
            area.varrer_orfas(AREA, idade=0)
            time.sleep(0.5)
        self.assertEqual(self.copias_na_area(), [])

    def test_varredura_ignora_o_que_nao_e_copia(self):
        alheia = AREA / "nao-mexer"
        alheia.mkdir(parents=True, exist_ok=True)
        try:
            area.varrer_orfas(AREA, idade=0)
            self.assertTrue(alheia.exists())
        finally:
            alheia.rmdir()

    def test_delegar_nao_repete_apos_timeout(self):
        cod, r = self.rodar(["modelo-lento", "modelo-ok"], papel="delegar", timeout=1)
        self.assertEqual(cod, 12)
        self.assertEqual([c[0] for c in chamadas()], ["modelo-lento"])

    def test_delegar_repete_apos_negado(self):
        cod, r = self.rodar(["modelo-jetski", "modelo-ok"], papel="delegar")
        self.assertEqual(cod, 0)

    def test_contraprova_nunca_usa_claude(self):
        self.rodar(["claude-opus-5-5-high", "gemini-ok"], papel="contraprova",
                   modelo="claude-sonnet-5-5-high")
        self.assertEqual([c[0] for c in chamadas()], ["gemini-ok"])

    def test_modelo_pedido_vai_primeiro(self):
        self.rodar(["modelo-ok", "modelo-ok2"], modelo="modelo-ok2")
        self.assertEqual(chamadas()[0][0], "modelo-ok2")

    def test_roda_na_copia_com_perfil_proprio(self):
        (TRAB / "calc.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
        self.rodar(["modelo-ok"])
        _m, cwd, modo, perfil, tem_settings, _diff = chamadas()[0]
        self.assertEqual(Path(cwd).resolve().parent, AREA.resolve())  # nunca a origem
        self.assertEqual(modo, "plan")
        self.assertTrue(Path(perfil).resolve().is_relative_to((TMP / "estado" / "perfis").resolve()))
        self.assertEqual(tem_settings, "True")
        # Copia e perfil somem ao fim da chamada.
        self.assertFalse(Path(cwd).exists())
        self.assertFalse(Path(perfil).exists())
        self.rodar(["modelo-ok"], papel="delegar")
        self.assertEqual(chamadas()[-1][2], "accept-edits")

    def test_delegar_devolve_patch_sem_tocar_origem(self):
        (TRAB / "calc.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
        cod, r = self.rodar(["modelo-edita"], papel="delegar")
        self.assertEqual(cod, 0)
        self.assertIn("a - b", (TRAB / "calc.py").read_text(encoding="utf-8"))
        self.assertFalse((TRAB / "novo.txt").exists())
        self.assertEqual(sorted(r["arquivos_alterados"]), ["calc.py", "novo.txt"])
        patch = Path(r["patch"]).read_text(encoding="utf-8")
        self.assertIn("+    return a + b", patch)
        self.assertEqual(list(AREA.glob("*/.git")), [])  # copia com .git somente-leitura apagada

    def test_diff_vai_como_arquivo_na_copia(self):
        repo = TMP / "repo-diff"
        repo.mkdir(exist_ok=True)
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run([*g, "add", "-A"], cwd=repo, check=True)
        subprocess.run([*g, "commit", "-qm", "c"], cwd=repo, check=True)
        os.environ["FAKE_MODELOS"] = "gemini-ok"  # contraprova so aceita gemini-*
        ponte.CASCATAS["contraprova"] = ["gemini-ok"]
        cod, r = ponte.executar("contraprova", "revise", repo, [], None, None, 30, diff_ref="HEAD")
        self.assertEqual(cod, 3)  # nada mudou: nem chama o agy
        self.assertEqual(chamadas(), [])
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        cod, r = ponte.executar("contraprova", "revise", repo, [], None, None, 30, diff_ref="HEAD")
        self.assertEqual(cod, 0)
        self.assertEqual(chamadas()[-1][5], "1")
        self.assertIn("ARGON_DIFF.patch", r["resposta"])

    def test_schema_devolve_estruturado(self):
        os.environ["FAKE_MODELOS"] = "modelo-ok"
        ponte.CASCATAS["explorar"] = ["modelo-ok"]
        cod, r = ponte.executar("explorar", "revise", TRAB, [], None, None, 30, schema=TMP / "argon.toml")
        self.assertEqual(cod, 0)
        self.assertEqual(r["estruturado"], {"ok": True})

    def test_aviso_de_sigilo_na_copia(self):
        (TRAB / "sub" / "anotacao.txt").write_text(f"titular {CPF_SINTETICO}\n", encoding="utf-8")
        try:
            cod, r = self.rodar(["modelo-ok"])
            self.assertEqual(cod, 0)  # aviso, nao bloqueio
            self.assertIn(str(Path("sub") / "anotacao.txt"), r["aviso_sigilo"]["arquivos_com_achado"])
        finally:
            (TRAB / "sub" / "anotacao.txt").unlink()

    def test_atalho_profundo_nao_e_copiado(self):
        d = TRAB / "fundo" / "nivel2"
        d.mkdir(parents=True, exist_ok=True)
        (CASOS / "caso-a" / "dado.txt").write_text("conteudo do caso\n", encoding="utf-8")
        if not criar_atalho(d / "atalho", CASOS / "caso-a"):
            self.skipTest("sem permissao para criar atalho")
        rel = area.listar_origem(TRAB)
        self.assertFalse(any("dado.txt" in str(p) for p in rel))

    def test_arquivo_fora_do_dir_bloqueia(self):
        fora = TMP / "fora.txt"
        fora.write_text("x\n", encoding="utf-8")
        self.assertEqual(self.rodar(["modelo-ok"], arquivos=[fora])[0], 20)

    # --- area isolada ---

    def test_complemento_nega_irmaos_e_preserva_o_caminho(self):
        alvo = AREA / "abc"
        alvo.mkdir(parents=True, exist_ok=True)
        (AREA / "irma").mkdir(exist_ok=True)
        regras = area.regras_de_complemento(alvo)
        barra = lambda p: str(p.resolve()).replace("\\", "/")
        self.assertIn(f"read_file({barra(AREA / 'irma')})", regras)
        self.assertIn(f"read_file({barra(CASOS)})", regras)       # irma de um ancestral
        self.assertIn(f"write_file({barra(CASOS)})", regras)
        for p in [alvo, *alvo.parents]:                            # nada no caminho e negado
            self.assertNotIn(f"read_file({barra(p)})", regras)
        self.assertIn("command(*)", regras)
        self.assertIn("mcp(*)", regras)

    def test_listar_origem_respeita_gitignore(self):
        repo = TMP / "repo"
        (repo / "node_modules").mkdir(parents=True, exist_ok=True)
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "segredo.log").write_text("ignorado\n", encoding="utf-8")
        (repo / "node_modules" / "m.js").write_text("y\n", encoding="utf-8")
        (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        nomes = sorted(str(p) for p in area.listar_origem(repo))
        self.assertEqual(nomes, [".gitignore", "a.py"])

    def test_guarda_impede_chamada(self):
        self.assertEqual(self.rodar(["modelo-ok"], cwd=CASOS / "caso-a")[0], 20)
        self.assertEqual(self.rodar(["modelo-ok"], cwd=TMP)[0], 20)
        self.assertEqual(self.rodar(["modelo-ok"], prompt=f"titular {CPF_SINTETICO}")[0], 20)
        self.assertEqual(chamadas(), [])

    def test_prompt_longo(self):
        self.assertEqual(self.rodar(["modelo-ok"], prompt="x" * (ponte.LIMITE_PROMPT + 1))[0], 16)

    def test_log_e_uso_gravados(self):
        cod, r = self.rodar(["modelo-ok"])
        self.assertTrue(Path(r["log"]).is_file())
        uso = (ponte.DIR_ESTADO / "uso.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(uso[-1])["modelo"], "modelo-ok")

    def test_classificar(self):
        self.assertEqual(ponte.classificar("Error: model foo is not recognized"), "modelo-ausente")
        self.assertEqual(ponte.classificar("", "Error: unknown model foo"), "modelo-ausente")
        self.assertEqual(ponte.classificar("  "), "vazio")
        self.assertEqual(ponte.classificar("jetski: no output produced", "", {"response": ""}), "negado")
        self.assertEqual(ponte.classificar("", "", {"response": "ok"}), "ok")
        self.assertEqual(ponte.ler_json_do_agy('jetski: x\n{"conversation_id":"c","response":"r"}')[1]["response"], "r")


class TestMain(unittest.TestCase):
    """Ponta a ponta pela linha de comando, como o despachante vai chamar."""

    def rodar(self, *args, entrada=None):
        ponte.CACHE_MODELOS.unlink(missing_ok=True)
        env = {**os.environ, "FAKE_MODELOS": "gemini-4-argon-medium"}
        r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "ponte.py"), *args],
                           input=entrada, capture_output=True, encoding="utf-8", env=env, timeout=120)
        return r.returncode, r.stdout

    def test_stdin_com_acento_chega_intacto(self):
        cod, out = self.rodar("--papel", "explorar", "--dir", str(TRAB), entrada="ação, pé, ênfase")
        self.assertEqual(cod, 0)
        self.assertIn("PROMPT=ação, pé, ênfase", json.loads(out)["resposta"])

    def test_dir_inexistente_e_uso(self):
        self.assertEqual(self.rodar("--papel", "explorar", "--dir", str(TMP / "nao"), "--prompt", "x")[0], 2)
        self.assertEqual(self.rodar("--papel", "explorar", "--modelo", "a/b", "--prompt", "x")[0], 2)

    def test_bloqueio_sai_20(self):
        cod, out = self.rodar("--papel", "explorar", "--dir", str(TRAB), "--prompt", f"titular {CPF_SINTETICO}")
        self.assertEqual(cod, 20)
        self.assertEqual(json.loads(out)["status"], "bloqueado")


if __name__ == "__main__":
    unittest.main()

"""Perguntas de "Me conta de você": ajudam o TITAN a conhecer o dono sem nada arriscado.

Nunca perguntam endereço, escola, documentos, contatos, dinheiro do banco, saúde,
intimidade ou dados de outras pessoas (e as respostas passam pelo filtro de safety).
"""

from __future__ import annotations

# chave, categoria, pergunta, opções rápidas (vazio = resposta livre)
QUESTIONS: list[tuple[str, str, str, list[str]]] = [
    ("aprende", "estudos", "Quando você aprende melhor: vendo vídeo, lendo ou fazendo na prática?",
     ["Vídeo", "Lendo", "Na prática"]),
    ("jeito", "sobre", "Prefere que eu seja mais direto ou mais na brincadeira?",
     ["Direto", "Na brincadeira", "Meio a meio"]),
    ("energia", "sobre", "Que hora do dia você tem mais energia?", ["Manhã", "Tarde", "Noite"]),
    ("curte", "gostos", "Qual jogo, série ou canal você mais curte agora?", []),
    ("dinheiro", "negocio", "Se o seu negócio der certo, o que você faria com o primeiro dinheiro?", []),
    ("materia_facil", "estudos", "Qual matéria você acha mais fácil?", []),
    ("materia_chata", "estudos", "E a matéria mais chata ou difícil?", []),
    ("um_ano", "sobre", "O que você quer estar fazendo daqui a 1 ano?", []),
    ("desanima", "sobre", "O que mais te desanima quando tenta fazer algo novo?", []),
    ("orgulho", "sobre", "Uma coisa que você já fez e ficou orgulhoso?", []),
    ("musica", "gostos", "Que tipo de música te dá ânimo?", []),
    ("habilidade", "sobre", "Uma coisa que você faz bem (ou que as pessoas te pedem ajuda)?", []),
    ("aprender", "estudos", "Uma coisa que você quer muito aprender?", []),
    ("negocio_ideia", "negocio", "Que tipo de negócio você mais tem vontade de tentar?",
     ["Vender produtos", "Serviço", "Internet/conteúdo", "Ainda não sei"]),
    ("tempo", "sobre", "Quanto tempo por dia dá para você dedicar aos seus projetos?",
     ["Menos de 30 min", "30 min a 1 h", "Mais de 1 h"]),
    ("cobranca", "sobre", "Quando você combina algo comigo, quer que eu te cobre?",
     ["Pode cobrar", "Só lembrar de leve", "Não cobra"]),
    ("comida", "gostos", "Qual sua comida favorita?", []),
    ("esporte", "gostos", "Curte algum esporte ou time?", []),
    ("rotina", "sobre", "Como é seu dia normal, em poucas palavras? (sem dizer onde)", []),
    ("sonho", "sobre", "Qual é um sonho grande seu?", []),
]

BY_KEY = {k: (cat, q, opts) for k, cat, q, opts in QUESTIONS}

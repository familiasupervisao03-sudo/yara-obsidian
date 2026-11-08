"""Pesquisa na internet (desligada por padrão; ver docs/pesquisa-internet.md).

Camadas: ``net`` (download seguro: só endereços públicos, portas 80/443, sem
cookies, limites de tamanho e tempo), ``extract`` (texto das páginas),
``search`` (fontes de busca), ``research`` (pesquisa completa para o chat).
Todo conteúdo vindo da internet é tratado como NÃO confiável.
"""

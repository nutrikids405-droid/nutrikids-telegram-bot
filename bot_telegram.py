import os
import re
import telebot
from telebot import types
import psycopg2
from datetime import datetime
import google.generativeai as genai

# ========== CONFIGURAÇÕES ==========
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
DATABASE_URL = os.environ.get('DATABASE_URL')
KIWIFY_CHECKOUT = os.environ.get('KIWIFY_CHECKOUT')

# Configurar Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# Inicializar bot
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Conexão com banco
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# ========== PROMPT ESPECIALIZADO ==========
PROMPT_BASE = """Você é NutriKids, especialista em receitas para crianças seletivas de 2-5 anos.

REGRAS DE SEGURANÇA OBRIGATÓRIAS:
1. NUNCA incluir mel para menores de 2 anos
2. NUNCA incluir oleaginosas inteiras (apenas trituradas)
3. Máximo 1 colher de sopa de açúcar por receita
4. Evitar excesso de sal
5. Sempre indicar cortar em pedaços pequenos
6. Preferir assado/cozido a frito

CONTEXTO DA CRIANÇA:
{contexto}

Crie 3 receitas que a criança VAI ACEITAR baseadas no que ela JÁ COME.

FORMATO DA RESPOSTA:

🍽️ *RECEITA 1: [Nome Divertido]*

📝 *Ingredientes:*
• [ingrediente com medida caseira]
• [fáceis de achar no mercado]

👩‍🍳 *Modo de Preparo:*
1. [passo simples]
2. [com tempo]

🎨 *Dica Mágica:*
[Como apresentar para a criança aceitar]

⏰ *Tempo:* [máximo 20 min]
💡 *Truque:* [como esconde nutrientes]

---

[Repetir para mais 2 receitas]

⚠️ Sempre supervisione crianças durante refeições. Consulte pediatra para restrições específicas."""

# ========== CRIAR TABELAS ==========
def criar_tabelas():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios_telegram (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            nome_crianca TEXT,
            idade_crianca INTEGER,
            status TEXT DEFAULT 'trial',
            trial_receitas INTEGER DEFAULT 0,
            alimentos_aceitos TEXT,
            alimentos_recusados TEXT,
            assinante_desde TIMESTAMP,
            criado_em TIMESTAMP DEFAULT NOW()
        )
    """)
    
    conn.commit()
    cur.close()
    conn.close()

# ========== FUNÇÕES DO BANCO ==========
def obter_usuario(telegram_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, nome_crianca, idade_crianca, status, trial_receitas, 
               alimentos_aceitos, alimentos_recusados
        FROM usuarios_telegram WHERE telegram_id = %s
    """, (telegram_id,))
    
    user = cur.fetchone()
    
    if not user:
        cur.execute(
            "INSERT INTO usuarios_telegram (telegram_id) VALUES (%s) RETURNING id",
            (telegram_id,)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {
            'id': user_id,
            'status': 'trial',
            'trial_receitas': 0,
            'nome_crianca': None
        }
    
    cur.close()
    conn.close()
    
    return {
        'id': user[0],
        'nome_crianca': user[1],
        'idade_crianca': user[2],
        'status': user[3],
        'trial_receitas': user[4],
        'alimentos_aceitos': user[5],
        'alimentos_recusados': user[6]
    }

def salvar_preferencias(telegram_id, campo, valor):
    conn = get_db_connection()
    cur = conn.cursor()
    
    query = f"UPDATE usuarios_telegram SET {campo} = %s WHERE telegram_id = %s"
    cur.execute(query, (valor, telegram_id))
    
    conn.commit()
    cur.close()
    conn.close()

def incrementar_trial(telegram_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute(
        "UPDATE usuarios_telegram SET trial_receitas = trial_receitas + 1 WHERE telegram_id = %s",
        (telegram_id,)
    )
    
    conn.commit()
    cur.close()
    conn.close()

def ativar_assinatura(telegram_id, email):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute(
        """UPDATE usuarios_telegram 
        SET status = 'pro', assinante_desde = NOW() 
        WHERE telegram_id = %s""",
        (telegram_id,)
    )
    
    conn.commit()
    cur.close()
    conn.close()

# ========== GERAR RECEITAS ==========
def gerar_receitas(user_data):
    contexto = f"""
    Criança: {user_data.get('nome_crianca', 'Criança')}, {user_data.get('idade_crianca', 3)} anos
    ACEITA: {user_data.get('alimentos_aceitos', 'nugget, macarrão')}
    RECUSA: {user_data.get('alimentos_recusados', 'vegetais verdes')}
    """
    
    prompt = PROMPT_BASE.format(contexto=contexto)
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return "❌ Erro ao gerar receitas. Tente novamente em alguns segundos."

# ========== HANDLERS DO BOT ==========

@bot.message_handler(commands=['start', 'inicio'])
def cmd_start(message):
    telegram_id = message.from_user.id
    user = obter_usuario(telegram_id)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🍳 Gerar Receitas')
    btn2 = types.KeyboardButton('📊 Meu Status')
    btn3 = types.KeyboardButton('⭐ Assinar PRO')
    btn4 = types.KeyboardButton('❓ Ajuda')
    markup.add(btn1, btn2, btn3, btn4)
    
    texto = f"""🧸 *Olá, {message.from_user.first_name}!*

Bem-vindo ao *NutriKids* - seu assistente de receitas infantis com IA!

*Como funciono:*
1️⃣ Você me diz o nome e idade da criança
2️⃣ Me conta o que ela come e não come
3️⃣ Eu crio receitas personalizadas que ela VAI aceitar!

*Planos:*
🆓 *Grátis:* 3 receitas para testar
⭐ *PRO:* Receitas ilimitadas - R$29,90/mês

*Vamos começar?*
Me diga o nome e idade do seu pequeno(a).

_Exemplo: Maria, 3 anos_"""
    
    bot.send_message(message.chat.id, texto, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['status'])
def cmd_status(message):
    telegram_id = message.from_user.id
    user = obter_usuario(telegram_id)
    
    if user['status'] == 'pro':
        texto = """⭐ *Você é PRO!* ⭐

✅ Receitas ilimitadas
✅ Suporte prioritário
✅ Acesso vitalício enquanto assinante

Digite ingredientes para gerar receitas! 🍳"""
    else:
        restantes = 3 - user['trial_receitas']
        texto = f"""📊 *Seu Status*

🆓 Plano: GRÁTIS
📝 Receitas usadas: {user['trial_receitas']}/3
🎯 Receitas restantes: {restantes}

💡 _Quer receitas ilimitadas?_
Use /assinar para conhecer o plano PRO!"""
    
    bot.send_message(message.chat.id, texto, parse_mode='Markdown')

@bot.message_handler(commands=['assinar'])
def cmd_assinar(message):
    texto = f"""⭐ *NUTRIKIDS PRO* ⭐

*Apenas R$ 29,90/mês*

✅ Receitas ilimitadas
✅ Acesso imediato após pagamento
✅ Sugestões exclusivas
✅ Cancele quando quiser

👉 *Assine agora:*
{KIWIFY_CHECKOUT}

*Como ativar:*
1. Clique no link acima
2. Faça o pagamento
3. Volte aqui e envie: /ativar seuemail@exemplo.com
4. Pronto! Acesso liberado! 🎉"""
    
    bot.send_message(message.chat.id, texto, parse_mode='Markdown')

@bot.message_handler(commands=['ativar'])
def cmd_ativar(message):
    telegram_id = message.from_user.id
    
    # Extrair email
    partes = message.text.split()
    if len(partes) < 2 or '@' not in partes[1]:
        bot.send_message(
            message.chat.id,
            "❌ Use: /ativar seuemail@gmail.com"
        )
        return
    
    email = partes[1]
    ativar_assinatura(telegram_id, email)
    
    texto = """🎉 *CONTA ATIVADA!* 🎉

Você agora é *PRO*! ⭐

✅ Receitas ilimitadas liberadas

*Digite ingredientes e aproveite!* 🍳"""
    
    bot.send_message(message.chat.id, texto, parse_mode='Markdown')

@bot.message_handler(commands=['ajuda', 'help'])
def cmd_ajuda(message):
    texto = """❓ *AJUDA - NUTRIKIDS*

*Comandos disponíveis:*
/start - Iniciar bot
/status - Ver seu plano
/assinar - Assinar PRO
/ativar - Ativar assinatura seuemail@gmail.com

*Dúvidas?* Entre em contato: suporte@nutrikids.com"""
    
    bot.send_message(message.chat.id, texto, parse_mode='Markdown')

# ========== HANDLER DE BOTÕES ==========

@bot.message_handler(func=lambda m: m.text == '🍳 Gerar Receitas')
def btn_gerar(message):
    telegram_id = message.from_user.id
    user = obter_usuario(telegram_id)
    
    if not user['nome_crianca']:
        texto = """*Vamos começar!*

Me diga o nome e idade do seu pequeno(a).

_Exemplo: João, 3 anos_"""
        bot.send_message(message.chat.id, texto, parse_mode='Markdown')
    else:
        texto = f"""Vou gerar receitas para *{user['nome_crianca']}*!

Digite novos ingredientes ou use os já salvos."""
        bot.send_message(message.chat.id, texto, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '📊 Meu Status')
def btn_status(message):
    cmd_status(message)

@bot.message_handler(func=lambda m: m.text == '⭐ Assinar PRO')
def btn_assinar(message):
    cmd_assinar(message)

@bot.message_handler(func=lambda m: m.text == '❓ Ajuda')
def btn_ajuda(message):
    cmd_ajuda(message)

# ========== PROCESSAR MENSAGENS DE TEXTO ==========

@bot.message_handler(func=lambda m: True)
def processar_texto(message):
    telegram_id = message.from_user.id
    texto = message.text.strip()
    user = obter_usuario(telegram_id)
    
    # ===== CAPTURAR NOME E IDADE =====
    if not user['nome_crianca'] and ('anos' in texto.lower() or 'ano' in texto.lower()):
        match = re.match(r'(.+?),?\s*(\d+)\s*anos?', texto, re.IGNORECASE)
        
        if match:
            nome_crianca = match.group(1).strip()
            idade = int(match.group(2))
            
            if idade < 2 or idade > 5:
                bot.send_message(
                    message.chat.id,
                    "⚠️ No momento, atendemos crianças de 2 a 5 anos.\n\n"
                    "Para outras idades, consulte um nutricionista infantil."
                )
                return
            
            salvar_preferencias(telegram_id, 'nome_crianca', nome_crianca)
            salvar_preferencias(telegram_id, 'idade_crianca', idade)
            
            texto = f"""✅ Ótimo! Vou criar receitas especiais para *{nome_crianca}*!

Agora me conta:
*O que {nome_crianca} GOSTA de comer?*

_Exemplo: nugget, macarrão, batata frita, pão_

💡 Dica: Liste tudo que ela aceita bem, mesmo que não seja "saudável"."""
            
            bot.send_message(message.chat.id, texto, parse_mode='Markdown')
            return
        else:
            bot.send_message(
                message.chat.id,
                "❌ Formato incorreto.\n\n*Use:* Nome, idade\n_Exemplo: Maria, 3 anos_",
                parse_mode='Markdown'
            )
            return
    
    # ===== CAPTURAR ALIMENTOS ACEITOS =====
    if user['nome_crianca'] and not user['alimentos_aceitos']:
        salvar_preferencias(telegram_id, 'alimentos_aceitos', texto)
        
        texto = f"""Perfeito! Agora me diga:

*O que {user['nome_crianca']} NÃO come de jeito nenhum?*

_Exemplo: brócolis, cenoura, carne vermelha, feijão_

Assim posso criar receitas que funcionam de verdade! 😊"""
        
        bot.send_message(message.chat.id, texto, parse_mode='Markdown')
        return
    
    # ===== CAPTURAR ALIMENTOS RECUSADOS E GERAR RECEITAS =====
    if user['alimentos_aceitos'] and not user['alimentos_recusados']:
        salvar_preferencias(telegram_id, 'alimentos_recusados', texto)
        
        # Verificar limite trial
        if user['status'] == 'trial' and user['trial_receitas'] >= 3:
            texto_limite = f"""⚠️ *Você já usou suas 3 receitas gratuitas!*

*Gostou das receitas?*
Tenha acesso ILIMITADO por apenas R$29,90/mês!

✅ Receitas novas todos os dias
✅ Cardápio semanal personalizado
✅ Acompanhamento da evolução alimentar
✅ Dicas exclusivas

*Assine agora:* {KIWIFY_CHECKOUT}

Após o pagamento, use: /ativar seuemail@gmail.com"""
            
            bot.send_message(message.chat.id, texto_limite, parse_mode='Markdown')
            return
        
        # Incrementar contador trial
        if user['status'] == 'trial':
            incrementar_trial(telegram_id)
        
        # Gerar receitas
        bot.send_message(
            message.chat.id,
            f"🍳 Preparando receitas especiais para *{user['nome_crianca']}*...\n\n"
            "⏰ Aguarde 10-15 segundos...",
            parse_mode='Markdown'
        )
        
        # Atualizar user com novos dados
        user['alimentos_recusados'] = texto
        
        receitas = gerar_receitas(user)
        bot.send_message(message.chat.id, receitas, parse_mode='Markdown')
        
        # Avisar receitas restantes se trial
        if user['status'] == 'trial':
            user_atualizado = obter_usuario(telegram_id)
            receitas_restantes = 3 - user_atualizado['trial_receitas']
            
            if receitas_restantes > 0:
                bot.send_message(
                    message.chat.id,
                    f"💡 *Receitas gratuitas restantes:* {receitas_restantes}/3\n\n"
                    "Digite 'mais' para gerar novas receitas!",
                    parse_mode='Markdown'
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "🎁 Essa foi sua última receita gratuita!\n\n"
                    "Assine para continuar gerando receitas ilimitadas!\n"
                    "Use: /assinar",
                    parse_mode='Markdown'
                )
        else:
            bot.send_message(
                message.chat.id,
                "✨ Quer mais receitas? Digite *mais*!\n"
                "📊 Ver progresso? Use /status",
                parse_mode='Markdown'
            )
        
        return
    
    # ===== COMANDO "MAIS" - GERAR NOVAS RECEITAS =====
    if texto.lower() in ['mais', 'outra', 'outra receita', 'gerar']:
        if not user['alimentos_aceitos']:
            bot.send_message(
                message.chat.id,
                "❌ Primeiro você precisa configurar as preferências!\n\nUse /start"
            )
            return
        
        # Verificar limite
        if user['status'] == 'trial' and user['trial_receitas'] >= 3:
            bot.send_message(
                message.chat.id,
                f"⚠️ Limite de receitas gratuitas atingido!\n\n"
                f"Assine em: {KIWIFY_CHECKOUT}\n\n"
                f"Depois use: /ativar seuemail@gmail.com",
                parse_mode='Markdown'
            )
            return
        
        if user['status'] == 'trial':
            incrementar_trial(telegram_id)
        
        bot.send_message(message.chat.id, "🍳 Gerando mais receitas...")
        receitas = gerar_receitas(user)
        bot.send_message(message.chat.id, receitas, parse_mode='Markdown')
        return
    
    # ===== ATIVAÇÃO DE ASSINATURA (EMAIL) =====
    if '@' in texto and '.' in texto:
        email = texto.strip()
        ativar_assinatura(telegram_id, email)
        
        bot.send_message(
            message.chat.id,
            "🎉 *ASSINATURA ATIVADA COM SUCESSO!*\n\n"
            f"Agora {user.get('nome_crianca', 'seu pequeno(a)')} tem receitas ilimitadas!\n\n"
            "Digite *mais* sempre que quiser novas receitas! 🍽️",
            parse_mode='Markdown'
        )
        return
    
    # ===== COMANDO NÃO RECONHECIDO =====
    bot.send_message(
        message.chat.id,
        "🤔 Não entendi seu pedido.\n\n"
        "Use os botões abaixo ou digite:\n"
        "• /start - Começar\n"
        "• /status - Ver plano\n"
        "• /assinar - Virar PRO\n"
        "• *mais* - Gerar receitas"
    )

# ========== INICIALIZAÇÃO ==========

if __name__ == '__main__':
    try:
        criar_tabelas()
        print("✅ Bot iniciado com sucesso!")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"❌ Erro ao iniciar bot: {e}")

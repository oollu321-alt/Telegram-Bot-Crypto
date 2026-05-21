import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv ('Token')
GROUP_CHAT_ID =  int(os.getenv('Chat_id'))  

user_targets = []
last_btc_checkpoint = None

def format_price(price):
    """Chote decimals wale coins ko sahi tareeqay se dikhane ke liye."""
    if price == 0:
        return "0.00"
    if price < 0.01:
        return f"{price:.8f}".rstrip('0').rstrip('.')
    elif price < 1:
        return f"{price:.4f}"
    else:
        return f"{price:,.2f}"

def get_binance_prices():
    """Binance API se prices fetch karne ka function (Error Handling ke sath)"""
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return {item['symbol']: float(item['price']) for item in data}
        else:
            logging.error(f"Binance API returned status code: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        
        logging.error(f"Binance Connection Error (Server slow/down): {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in get_binance_prices: {e}")
        return None

async def check_price_alert(context: ContextTypes.DEFAULT_TYPE):
    global user_targets, last_btc_checkpoint
    
    prices = get_binance_prices()
    if not prices:
        return  

    for target in user_targets[:]:
        symbol = f"{target['coin_symbol']}USDT".upper()
        target_price = target['target_price']
        username = target['user']
        condition = target['condition']
        
        current_price = prices.get(symbol)
        if not current_price:
            continue

        hit = False
        if condition == 'above' and current_price >= target_price:
            hit = True
        elif condition == 'below' and current_price <= target_price:
            hit = True

        if hit:
            msg = (
                f"🎉 🎯 TARGET HIT 🎯 🎉\n\n"
                f" @{username} {target['coin_symbol'].upper()} Has reached your target price \n\n"
                f"🚩 Target Price: {format_price(target_price)} USD\n"
                f"⚡ Current Price: {format_price(current_price)} USD 🚀"
            )
            try:
                await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="Markdown")
                user_targets.remove(target) 
            except Exception as e:
                logging.error(f"Could not send target hit message: {e}")

    
    btc_price = prices.get("BTCUSDT")
    if btc_price:
        current_checkpoint = int(btc_price // 500)
        
        if last_btc_checkpoint is None:
            last_btc_checkpoint = current_checkpoint
            return
            
        if current_checkpoint != last_btc_checkpoint:
            direction = "UP 🟢" if current_checkpoint > last_btc_checkpoint else "DOWN 🔴"
            boundary = current_checkpoint * 500 if direction == "UP 🟢" else (current_checkpoint + 1) * 500
            
            msg = (
                f"🚨Bitcoin is {direction} and crossed ${boundary:,.0f} \n\n"
                f"💸 Current BTC Price: ${format_price(btc_price)} USD\n\n"
            )
            
            
            majors = ['ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
            msg += "📊 Big Caps current prices:\n"
            for m in majors:
                if m in prices:
                    name = m.replace('USDT', '')
                    msg += f"🔹 {name}: ${format_price(prices[m])}\n"
                    
            
            if user_targets:
                msg += "\n⏳ Pending Targets Update: \n"
                for t in user_targets:
                    sym = f"{t['coin_symbol']}USDT".upper()
                    if sym in prices:
                        msg += f"🔸 {t['coin_symbol'].upper()} (@{t['user']}): ${format_price(prices[sym])} *(Target: {t['target_price']})*\n"
            
            try:
                await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="Markdown")
                last_btc_checkpoint = current_checkpoint
            except Exception as e:
                logging.error(f"Could not send BTC milestone message: {e}")

async def check_instant_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /price cion ya /check coin"""
    if not context.args:
        await update.message.reply_text("❌ Coin ka naam likhein.\n👉 Example: `/price eth` ya `/price btc`", parse_mode="Markdown")
        return

    user_input = context.args[0].upper().replace("USDT", "")
    symbol = f"{user_input}USDT"
    
    prices = get_binance_prices()
    if not prices:
        await update.message.reply_text("⚠️ Binance server se connection nahi ho paa raha. Kuch der baad try karein.", parse_mode="Markdown")
        return

    if symbol in prices:
        price = prices[symbol]
        await update.message.reply_text(
            f"📊 {user_input} :\n\n"
            f"💵 Current Price: ${format_price(price)} USD",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Binance par `{user_input}` ka USDT pair nahi mila.", parse_mode="Markdown")

async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /settarget"""
    if len(context.args) < 2:
        context.user_data['awaiting_target'] = True
        await update.message.reply_text(
            "📝 Target Alert Setup\n\n"
            "Target set karne ke liye coin ka naam aur price reply karein.\n"
            "👉 Example: ` eth 3200`", 
            parse_mode="Markdown"
        )
        return
        
    coin_input = context.args[0].lower().replace("usdt", "")
    price_input = context.args[1].replace(',', '')
    await process_target(update, context, coin_input, price_input)

async def delete_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /del_target"""
    global user_targets
    username = update.message.from_user.username or update.message.from_user.first_name
    
    my_targets = [t for t in user_targets if t['user'] == username]
    
    if not my_targets:
        await update.message.reply_text("❌ No active target currently.")
        return

    context.user_data['my_pending_targets'] = my_targets
    context.user_data['awaiting_delete_index'] = True
    
    msg = "Kaun sa target delete karna chahte hain? Number reply karein:\n\n"
    for idx, t in enumerate(my_targets, 1):
        msg += f"{idx}. {t['coin_symbol'].upper()} - Target: {t['target_price']}\n"
        
    await update.message.reply_text(msg)

async def handle_text_for_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches simple text replies if user typed /settarget alone or wants to delete"""
    if context.user_data.get('awaiting_delete_index'):
        user_input = update.message.text.strip()
        my_targets = context.user_data.get('my_pending_targets', [])
        
        try:
            choice = int(user_input) - 1
            if 0 <= choice < len(my_targets):
                target_to_remove = my_targets[choice]
                global user_targets
                user_targets.remove(target_to_remove)
                
                await update.message.reply_text(f"🗑️ Target {target_to_remove['coin_symbol'].upper()} ({target_to_remove['target_price']}) deleted.")
                context.user_data['awaiting_delete_index'] = False
            else:
                await update.message.reply_text("❌ Galat number. Sahi number likhein.")
        except ValueError:
            await update.message.reply_text("❌ Sirf number likhein.")
        return

    if context.user_data.get('awaiting_target'):
        text = update.message.text.strip().split()
        if len(text) == 2:
            coin_input = text[0].lower().replace("usdt", "")
            price_input = text[1].replace(',', '')
            await process_target(update, context, coin_input, price_input)
            context.user_data['awaiting_target'] = False
        else:
            await update.message.reply_text("❌ Format sahi nahi hai. Dobara sahi se likhein (e.g., `/settarget eth 3200`).", parse_mode="Markdown")

async def process_target(update, context, coin_input, price_input):
    global user_targets
    symbol = f"{coin_input}USDT".upper()
    
    try:
        target_price = float(price_input)
        prices = get_binance_prices()
        
        if not prices or symbol not in prices:
            await update.message.reply_text(f"❌ Binance par `{coin_input.upper()}` ka pair nahi mila.", parse_mode="Markdown")
            return
            
        current_price = prices[symbol]
        condition = 'above' if target_price > current_price else 'below'
        username = update.message.from_user.username or update.message.from_user.first_name
        
        user_targets.append({
            'user': username,
            'coin_symbol': coin_input,
            'target_price': target_price,
            'condition': condition
        })
        
        direction_text = "UP 🟢" if condition == 'above' else "DOWN 🔴"
        await update.message.reply_text(
            f"✅ Target Saved Successfully!\n\n"
            f"👤 @{username}\n"
            f"🪙 Coin: {coin_input.upper()}\n"
            f"🎯 Target Price: {format_price(target_price)}\n"
            f"When price will go {direction_text} from your set target you will be notified.",
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Price ka format thik nahi hai. Sahi number likhein.", parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /status - Shows active targets and current BTC price"""
    global user_targets
    prices = get_binance_prices()
    
    if not prices:
        await update.message.reply_text("⚠️ Binance server temporary busy hai. Live status check nahi ho saka.")
        return
        
    btc_price = prices.get("BTCUSDT", 0)
    
    status_text = "📊 LIVE BOT STATUS 📊\n\n"
    status_text += f"🪙 Bitcoin (BTC): ${format_price(btc_price)} USD\n"
    status_text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    status_text += "🎯 Active Targets Monitoring:\n"
    
    if not user_targets:
        status_text += "❌ No active target currently."
    else:
        for i, t in enumerate(user_targets, 1):
            sym = f"{t['coin_symbol']}USDT".upper()
            curr = format_price(prices.get(sym, 0)) if sym in prices else "N/A"
            status_text += f"{i}️⃣ @{t['user']} ➔ {t['coin_symbol'].upper()}\n"
            status_text += f"    🏁 Target: `{format_price(t['target_price'])}` | ⏱️ Live: `${curr}`\n\n"
            
    await update.message.reply_text(status_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /help"""
    help_text = (
        "🤖 **Crypto Alert Bot Menu** 🤖\n\n"
        "Aap niche di gayi commands use kar sakte hain:\n\n"
        "📈 `/price [coin]` - Kisi bhi coin ki live price instantly check karein.\n"
        "👉 *Example:* `/price btc` ya `/price eth`\n\n"
        "🎯 `/settarget [coin] [price]` - Apne coin ka price alert set karein us price par ham apko alert kra ga.\n"
        "👉 *Example:* `/settarget eth 3200` ya sirf `/settarget` bhej kar bot instructions follow karein.\n\n"
        "🗑️ `/del_target` - Apne kisi bhi active target ko delete karein.\n\n"
        "📊 `/status` - BTC ki price aur chal rahe saare active alerts ka dashboard dekhein.\n\n"
        "❓ `/help` - Is menu ko dobara dekhne ke liye."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def post_init(application: Application) -> None:
    
    application.job_queue.run_repeating(check_price_alert, interval=60, first=3)
    print("Polished Binance tracking job initialized successfully.")

def main():
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    
    application.add_handler(CommandHandler("price", check_instant_price))
    application.add_handler(CommandHandler("check", check_instant_price))  
    application.add_handler(CommandHandler("settarget", set_target))
    application.add_handler(CommandHandler("del_target", delete_target))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_for_target))

    print("Bot is up and running 🎊......")
    application.run_polling()

if __name__ == '__main__':
    main()
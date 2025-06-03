import logging
import json
import re
import sqlite3
import os
from pathlib import Path
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
)

# Set up logging to output to stdout for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Output to stdout
    ]
)
logger = logging.getLogger(__name__)

# Bot token and admin IDs
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ Ошибка: Не задан BOT_TOKEN! Добавь его в настройки Render.")
    raise ValueError("❌ Ошибка: Не задан BOT_TOKEN! Добавь его в настройки Render.")
ADMIN_IDS = [6247655284]  # Only one admin for testing

# Cafe address
CAFE_ADDRESS = "Street 608"

# States for the conversation (steps of the order process)
CATEGORY, ITEM, CART, REMOVE, DELIVERY, ADDRESS, NAME, TABLE, PHONE, CONFIRM = range(10)

# Cafe menu
MENU = {
    "Ice Drinks": [
        {"name": "Ice Americano", "price": 1.75},
        {"name": "Ice Latte", "price": 1.75},
        {"name": "Ice Cappuccino", "price": 1.75},
        {"name": "Ice Honey Black Coffee", "price": 1.75},
        {"name": "Ice Honey Lemon Coffee", "price": 1.75},
        {"name": "Ice Matcha Latte", "price": 1.75},
        {"name": "Ice Honey Lemon Tea", "price": 1.75},
        {"name": "Ice Green Tea", "price": 1.75},
        {"name": "Ice Fresh Milk", "price": 1.75},
        {"name": "Ice Strawberry Matcha", "price": 1.75},
        {"name": "Ice Strawberry Chocolate", "price": 2.00},
        {"name": "Ice Chocolate", "price": 2.00}
    ],
    "Hot Drinks": [
        {"name": "Hot Latte", "price": 1.75},
        {"name": "Hot Chocolate", "price": 1.75},
        {"name": "Hot Matcha", "price": 1.75},
        {"name": "Hot Green Tea", "price": 1.75},
        {"name": "Hot Cappuccino", "price": 1.75},
        {"name": "Hot Americano", "price": 1.75},
        {"name": "Hot Fresh Milk", "price": 1.75}
    ],
    "Soda": [
        {"name": "Kiwi Soda", "price": 1.75},
        {"name": "Lime Soda", "price": 1.75},
        {"name": "Lychee Soda", "price": 1.75},
        {"name": "Strawberry Soda", "price": 1.75},
        {"name": "Passion Soda", "price": 1.75}
    ],
    "Smoothies": [
        {"name": "Strawberry Smoothie", "price": 2.00},
        {"name": "Passion Smoothie", "price": 2.00},
        {"name": "Kiwi Smoothie", "price": 2.00},
        {"name": "Lychee Smoothie", "price": 2.00}
    ],
    "Frappe": [
        {"name": "Cappuccino Frappe", "price": 2.00},
        {"name": "Latte Frappe", "price": 2.00},
        {"name": "Chocolate Frappe", "price": 2.00},
        {"name": "Fresh Milk Frappe", "price": 2.00}
    ]
}

# Create 'data' directory if it doesn't exist
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Path to the database
DB_PATH = DATA_DIR / "orders.db"

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                items TEXT,
                total_price REAL,
                delivery TEXT,
                address TEXT,
                table_number TEXT,
                name TEXT,
                phone TEXT
            )
        """)
        
        # User states table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state INTEGER,
                cart TEXT,
                delivery TEXT,
                address TEXT,
                name TEXT,
                table_number TEXT,
                phone TEXT,
                last_updated TEXT
            )
        """)
        
        # Error logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                error TEXT,
                timestamp TEXT,
                state TEXT
            )
        """)
        
        conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

# Save user state to database
def save_user_state(user_id, context_data):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO user_states 
            (user_id, state, cart, delivery, address, name, table_number, phone, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            context_data.get("state"),
            json.dumps(context_data.get("cart", [])),
            context_data.get("delivery"),
            context_data.get("address"),
            context_data.get("name"),
            context_data.get("table"),
            context_data.get("phone"),
            datetime.now().isoformat()
        ))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save user state: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

# Load user state from database
def load_user_state(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM user_states WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row:
            return {
                "state": row[1],
                "cart": json.loads(row[2]) if row[2] else [],
                "delivery": row[3],
                "address": row[4],
                "name": row[5],
                "table": row[6],
                "phone": row[7]
            }
        return None
    except Exception as e:
        logger.error(f"Failed to load user state: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()

# Log error to database
def log_error(user_id, error, state=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO error_logs (user_id, error, timestamp, state)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            str(error),
            datetime.now().isoformat(),
            str(state)
        ))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

# Save order to database
def save_to_db(order):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO orders (date, items, total_price, delivery, address, table_number, name, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order["Date"],
            json.dumps(order["Items"]),
            order["Total Price"],
            order["Delivery"],
            order["Address"],
            order["Table"],
            order["Name"],
            order["Phone"]
        ))
        
        conn.commit()
        logger.info("Order saved to database successfully.")
    except Exception as e:
        logger.error(f"Failed to save order to database: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

# Get recent orders from database
def get_recent_orders():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 5")
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"Failed to get recent orders: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

# Command /orders (for admins only)
async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Sorry, this command is only available to admins! 😊")
            logger.info(f"User {user_id} attempted to access /orders but is not an admin.")
            return

        orders = get_recent_orders()
        if not orders:
            await update.message.reply_text("No orders found.")
            return

        response = "Recent Orders (last 5):\n\n"
        for order in orders:
            order_id, date, items_json, total_price, delivery, address, table_number, name, phone = order
            items = json.loads(items_json)
            cart_summary = "\n".join([f"- {item['name']} — {item['price']} $" for item in items])
            
            order_details = (
                f"Order ID: {order_id}\n"
                f"Date: {date}\n"
                f"Drinks:\n{cart_summary}\n"
                f"Total: {total_price:.2f} $\n"
                f"Method: {delivery}\n"
            )
            
            if delivery == "Delivery":
                order_details += f"Address: {address}\n"
            elif delivery == "Drink On-Site":
                order_details += f"Table Number: {table_number}\n"
                
            order_details += (
                f"Name: {name}\n"
                f"Phone: {phone}\n"
                f"{'-' * 30}\n"
            )
            response += order_details

        await update.message.reply_text(response)
        logger.info(f"Admin {user_id} viewed recent orders.")
    except Exception as e:
        logger.error(f"Error in orders command: {e}")
        log_error(update.effective_user.id, e, "orders")
        await update.message.reply_text("Something went wrong while fetching orders. Please try again! 😊")

# Command /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        logger.info(f"Received /start from user {user_id}")
        
        # Clear any existing state
        context.user_data.clear()
        
        # Initialize fresh state
        initial_state = {
            "state": CATEGORY,
            "cart": [],
            "delivery": None,
            "address": None,
            "name": None,
            "table": None,
            "phone": None
        }
        
        # Save to database
        save_user_state(user_id, initial_state)
        context.user_data.update(initial_state)
        
        # Show menu categories
        keyboard = [[category] for category in MENU.keys()]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await update.message.reply_text(
            f"Hello! 😊 Welcome to One Shot Cafe!\nWe are located at: {CAFE_ADDRESS}\nChoose a category:",
            reply_markup=reply_markup
        )
        
        return CATEGORY
    except Exception as e:
        logger.error(f"Error in start for user {user_id}: {e}")
        log_error(update.effective_user.id, e, "start")
        await update.message.reply_text("Something went wrong. Please try again later! 😊")
        return ConversationHandler.END

# Select category
async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            saved_state = load_user_state(user_id)
            if saved_state:
                context.user_data.update(saved_state)
                return saved_state["state"]
            return await start(update, context)
        
        # Validate category
        if text not in MENU:
            await update.message.reply_text("Oops, please choose a category from the list! 😊")
            return CATEGORY
        
        # Update state
        context.user_data.update({
            "state": CATEGORY,
            "category": text
        })
        save_user_state(user_id, context.user_data)
        
        # Prepare items list
        items = MENU[text]
        items_list = "\n".join([f"{i+1}. {item['name']} — {item['price']} $" for i, item in enumerate(items)])
        
        # Create keyboard
        keyboard = []
        row = []
        for item in items:
            row.append(item['name'])
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append(["Back"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await update.message.reply_text(
            f"Choose a drink from the category {text}:\n\n{items_list}\n\nTap on the drink name below:",
            reply_markup=reply_markup
        )
        
        context.user_data["state"] = ITEM
        save_user_state(user_id, context.user_data)
        
        return ITEM
    except Exception as e:
        logger.error(f"Error in select_category: {e}")
        log_error(update.effective_user.id, e, "select_category")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Select drink
async def select_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            context.user_data["state"] = CATEGORY
            save_user_state(user_id, context.user_data)
            
            keyboard = [[category] for category in MENU.keys()]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            
            await update.message.reply_text(
                "Choose a category:",
                reply_markup=reply_markup
            )
            return CATEGORY
        
        # Find selected item
        category = context.user_data.get("category")
        if not category:
            await update.message.reply_text("Category not found. Let's start over.")
            return await start(update, context)
            
        items = MENU.get(category, [])
        item = next((i for i in items if i["name"] == text), None)
        
        if not item:
            await update.message.reply_text("Please choose a drink from the list! 😊")
            return ITEM
        
        # Update cart
        if "cart" not in context.user_data or not isinstance(context.user_data["cart"], list):
            context.user_data["cart"] = []
            
        context.user_data["cart"].append({"name": item["name"], "price": item["price"]})
        save_user_state(user_id, context.user_data)
        
        # Show cart summary
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in context.user_data["cart"]])
        total_price = sum(drink["price"] for drink in context.user_data["cart"])
        
        await update.message.reply_text(
            f"Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
            reply_markup=ReplyKeyboardMarkup(
                [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                one_time_keyboard=True
            )
        )
        
        context.user_data["state"] = CART
        save_user_state(user_id, context.user_data)
        
        return CART
    except Exception as e:
        logger.error(f"Error in select_item: {e}")
        log_error(update.effective_user.id, e, "select_item")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Cart actions
async def cart_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            category = context.user_data.get("category")
            if not category:
                return await start(update, context)
                
            items = MENU[category]
            items_list = "\n".join([f"{i+1}. {item['name']} — {item['price']} $" for i, item in enumerate(items)])
            
            keyboard = []
            row = []
            for item in items:
                row.append(item['name'])
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append(["Back"])
            
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            
            await update.message.reply_text(
                f"Choose a drink from the category {category}:\n\n{items_list}\n\nTap on the drink name below:",
                reply_markup=reply_markup
            )
            
            context.user_data["state"] = ITEM
            save_user_state(user_id, context.user_data)
            
            return ITEM
        
        # Handle actions
        if text == "Add More Drinks":
            keyboard = [[category] for category in MENU.keys()]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            
            await update.message.reply_text(
                "Choose another category:",
                reply_markup=reply_markup
            )
            
            context.user_data["state"] = CATEGORY
            save_user_state(user_id, context.user_data)
            
            return CATEGORY
            
        elif text == "Remove a Drink":
            cart = context.user_data.get("cart", [])
            if not cart:
                await update.message.reply_text("Your cart is empty! Let's add some drinks.")
                return CATEGORY
                
            keyboard = [[drink["name"] for drink in cart]] + [["Back to Cart"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            
            cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
            
            await update.message.reply_text(
                f"Your cart:\n{cart_summary}\n\nWhich drink would you like to remove?",
                reply_markup=reply_markup
            )
            
            context.user_data["state"] = REMOVE
            save_user_state(user_id, context.user_data)
            
            return REMOVE
            
        elif text == "Place Order":
            cart = context.user_data.get("cart", [])
            if not cart:
                await update.message.reply_text("Your cart is empty! Let's add some drinks.")
                return CATEGORY
                
            keyboard = [["Delivery"], ["Pickup"], ["Drink On-Site"], ["Back"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            
            await update.message.reply_text(
                "How would you like to receive your order?", 
                reply_markup=reply_markup
            )
            
            context.user_data["state"] = DELIVERY
            save_user_state(user_id, context.user_data)
            
            return DELIVERY
            
        else:
            await update.message.reply_text("Please choose an option!")
            return CART
    except Exception as e:
        logger.error(f"Error in cart_action: {e}")
        log_error(update.effective_user.id, e, "cart_action")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Remove a drink from the cart
async def remove_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back to Cart":
            cart = context.user_data.get("cart", [])
            cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
            total_price = sum(drink["price"] for drink in cart)
            
            await update.message.reply_text(
                f"Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                    one_time_keyboard=True
                )
            )
            
            context.user_data["state"] = CART
            save_user_state(user_id, context.user_data)
            
            return CART
            
        # Remove the selected drink
        cart = context.user_data.get("cart", [])
        context.user_data["cart"] = [drink for drink in cart if drink["name"] != text]
        save_user_state(user_id, context.user_data)
        
        # Show updated cart
        updated_cart = context.user_data["cart"]
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in updated_cart])
        total_price = sum(drink["price"] for drink in updated_cart)
        
        await update.message.reply_text(
            f"Drink removed! Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
            reply_markup=ReplyKeyboardMarkup(
                [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                one_time_keyboard=True
            )
        )
        
        context.user_data["state"] = CART
        save_user_state(user_id, context.user_data)
        
        return CART
    except Exception as e:
        logger.error(f"Error in remove_item: {e}")
        log_error(update.effective_user.id, e, "remove_item")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Select delivery method
async def select_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            cart = context.user_data.get("cart", [])
            cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
            total_price = sum(drink["price"] for drink in cart)
            
            await update.message.reply_text(
                f"Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                    one_time_keyboard=True
                )
            )
            
            context.user_data["state"] = CART
            save_user_state(user_id, context.user_data)
            
            return CART
            
        # Validate delivery method
        if text not in ["Delivery", "Pickup", "Drink On-Site"]:
            await update.message.reply_text("Choose 'Delivery', 'Pickup', or 'Drink On-Site'! 😊")
            return DELIVERY
            
        # Update state
        context.user_data.update({
            "delivery": text,
            "state": DELIVERY
        })
        save_user_state(user_id, context.user_data)
        
        if text == "Delivery":
            await update.message.reply_text(
                "Enter your delivery address:",
                reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
            )
            
            context.user_data["state"] = ADDRESS
            save_user_state(user_id, context.user_data)
            
            return ADDRESS
        else:
            await update.message.reply_text(
                "Enter your name:",
                reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
            )
            
            context.user_data["state"] = NAME
            save_user_state(user_id, context.user_data)
            
            return NAME
    except Exception as e:
        logger.error(f"Error in select_delivery: {e}")
        log_error(update.effective_user.id, e, "select_delivery")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Enter address (for delivery only)
async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            keyboard = [["Delivery"], ["Pickup"], ["Drink On-Site"], ["Back"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            
            await update.message.reply_text(
                "How would you like to receive your order?",
                reply_markup=reply_markup
            )
            
            context.user_data["state"] = DELIVERY
            save_user_state(user_id, context.user_data)
            
            return DELIVERY
            
        # Save address
        context.user_data.update({
            "address": text,
            "state": ADDRESS
        })
        save_user_state(user_id, context.user_data)
        
        await update.message.reply_text(
            "Enter your name:",
            reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
        )
        
        context.user_data["state"] = NAME
        save_user_state(user_id, context.user_data)
        
        return NAME
    except Exception as e:
        logger.error(f"Error in get_address: {e}")
        log_error(update.effective_user.id, e, "get_address")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Enter name
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            if context.user_data.get("delivery") == "Delivery":
                await update.message.reply_text(
                    "Enter your delivery address:",
                    reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
                )
                
                context.user_data["state"] = ADDRESS
                save_user_state(user_id, context.user_data)
                
                return ADDRESS
            else:
                keyboard = [["Delivery"], ["Pickup"], ["Drink On-Site"], ["Back"]]
                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
                
                await update.message.reply_text(
                    "How would you like to receive your order?",
                    reply_markup=reply_markup
                )
                
                context.user_data["state"] = DELIVERY
                save_user_state(user_id, context.user_data)
                
                return DELIVERY
                
        # Save name
        context.user_data.update({
            "name": text,
            "state": NAME
        })
        save_user_state(user_id, context.user_data)
        
        if context.user_data.get("delivery") == "Drink On-Site":
            await update.message.reply_text(
                "Enter your table number (1-20):",
                reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
            )
            
            context.user_data["state"] = TABLE
            save_user_state(user_id, context.user_data)
            
            return TABLE
            
        await update.message.reply_text(
            "Enter your phone number (e.g., +1234567890):",
            reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
        )
        
        context.user_data["state"] = PHONE
        save_user_state(user_id, context.user_data)
        
        return PHONE
    except Exception as e:
        logger.error(f"Error in get_name: {e}")
        log_error(update.effective_user.id, e, "get_name")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Enter table number (for on-site orders)
async def get_table(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            await update.message.reply_text(
                "Enter your name:",
                reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
            )
            
            context.user_data["state"] = NAME
            save_user_state(user_id, context.user_data)
            
            return NAME
            
        # Validate table number
        try:
            table_num = int(text)
            if not 1 <= table_num <= 20:
                await update.message.reply_text("Please enter a table number between 1 and 20!")
                return TABLE
        except ValueError:
            await update.message.reply_text("Please enter a valid table number (e.g., 5)!")
            return TABLE
            
        # Save table number
        context.user_data.update({
            "table": text,
            "state": TABLE
        })
        save_user_state(user_id, context.user_data)
        
        # Show order summary
        cart = context.user_data.get("cart", [])
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
        total_price = sum(drink["price"] for drink in cart)
        
        order_summary = (
            f"Your order:\n"
            f"Drinks:\n{cart_summary}\n"
            f"Total: {total_price:.2f} $\n"
            f"Method: {context.user_data.get('delivery')}\n"
            f"Table Number: {context.user_data.get('table', 'Not specified')}\n"
            f"Name: {context.user_data.get('name')}\n"
            f"Everything correct? (Yes/No)"
        )
        
        keyboard = [["Yes"], ["No"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await update.message.reply_text(
            order_summary,
            reply_markup=reply_markup
        )
        
        context.user_data["state"] = CONFIRM
        save_user_state(user_id, context.user_data)
        
        return CONFIRM
    except Exception as e:
        logger.error(f"Error in get_table: {e}")
        log_error(update.effective_user.id, e, "get_table")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Enter phone number (for Delivery and Pickup only)
async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        # Handle Back command
        if text == "Back":
            await update.message.reply_text(
                "Enter your name:",
                reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True)
            )
            
            context.user_data["state"] = NAME
            save_user_state(user_id, context.user_data)
            
            return NAME
            
        # Validate phone number
        if not re.match(r"^\+?\d{10,15}$", text):
            await update.message.reply_text("Oops, please enter a valid phone number (e.g., +1234567890)! 😊")
            return PHONE
            
        # Save phone number
        context.user_data.update({
            "phone": text,
            "state": PHONE
        })
        save_user_state(user_id, context.user_data)
        
        # Show order summary
        cart = context.user_data.get("cart", [])
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
        total_price = sum(drink["price"] for drink in cart)
        
        order_summary = (
            f"Your order:\n"
            f"Drinks:\n{cart_summary}\n"
            f"Total: {total_price:.2f} $\n"
            f"Method: {context.user_data.get('delivery')}\n"
        )
        
        if context.user_data.get("delivery") == "Delivery":
            order_summary += f"Address: {context.user_data.get('address', 'Not specified')}\n"
        elif context.user_data.get("delivery") == "Drink On-Site":
            order_summary += f"Table Number: {context.user_data.get('table', 'Not specified')}\n"
            
        order_summary += (
            f"Name: {context.user_data.get('name')}\n"
            f"Phone: {context.user_data.get('phone')}\n"
            f"Everything correct? (Yes/No)"
        )
        
        keyboard = [["Yes"], ["No"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        await update.message.reply_text(
            order_summary,
            reply_markup=reply_markup
        )
        
        context.user_data["state"] = CONFIRM
        save_user_state(user_id, context.user_data)
        
        return CONFIRM
    except Exception as e:
        logger.error(f"Error in get_phone: {e}")
        log_error(update.effective_user.id, e, "get_phone")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Confirm order
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        if text == "Yes":
            # Verify all required data exists
            required_fields = ["cart", "delivery", "name"]
            for field in required_fields:
                if field not in context.user_data:
                    await update.message.reply_text("Oops, something went wrong with your order. Let's start over!")
                    return await start(update, context)
                    
            # Create order
            cart = context.user_data["cart"]
            total_price = sum(drink["price"] for drink in cart)
            
            order = {
                "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Items": cart,
                "Total Price": total_price,
                "Delivery": context.user_data["delivery"],
                "Address": context.user_data.get("address", "Not specified"),
                "Table": context.user_data.get("table", "Not specified"),
                "Name": context.user_data["name"],
                "Phone": context.user_data.get("phone", "Not provided"),
            }
            
            # Save to database
            save_to_db(order)
            
            # Notify admins
            cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
            order_summary = (
                f"New order:\n"
                f"Date: {order['Date']}\n"
                f"Drinks:\n{cart_summary}\n"
                f"Total: {total_price:.2f} $\n"
                f"Method: {order['Delivery']}\n"
            )
            
            if order["Delivery"] == "Delivery":
                order_summary += f"Address: {order['Address']}\n"
            elif order["Delivery"] == "Drink On-Site":
                order_summary += f"Table Number: {order['Table']}\n"
                
            order_summary += (
                f"Name: {order['Name']}\n"
                f"Phone: {order['Phone']}"
            )
            
            if order["Delivery"] == "Pickup":
                order_summary += f"\nPickup Location: {CAFE_ADDRESS}"
                
            # Send to all admins
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=order_summary)
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
                    log_error(admin_id, e, "admin_notification")
            
            # Confirm to user
            confirmation_message = (
                f"Great! Your order is placed! Thank you! 😊\n"
                f"Please pick up your order at: {CAFE_ADDRESS}\n\n"
                f"To place another order, tap the button below or type /start!"
            )
            
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("Place Another Order", callback_data="restart")]
            ])
            
            await update.message.reply_text(confirmation_message, reply_markup=reply_markup)
            
            # Clear user data
            context.user_data.clear()
            
            # Remove saved state from database
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to clear user state from DB: {e}")
            
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "Order canceled. Type /start to begin again! 😊",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Clear user data
            context.user_data.clear()
            
            # Remove saved state from database
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to clear user state from DB: {e}")
            
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in confirm_order: {e}")
        log_error(update.effective_user.id, e, "confirm_order")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return await start(update, context)

# Handle inline button clicks
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "restart":
            # Clear user data and restart
            context.user_data.clear()
            
            # Remove saved state from database
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user_states WHERE user_id = ?", (query.from_user.id,))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to clear user state from DB: {e}")
            
            keyboard = [[category] for category in MENU.keys()]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            
            await query.message.reply_text(
                f"Hello! 😊 Welcome to One Shot Cafe!\nWe are located at: {CAFE_ADDRESS}\nChoose a category:",
                reply_markup=reply_markup
            )
            return CATEGORY
            
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in handle_button: {e}")
        log_error(update.effective_user.id, e, "handle_button")
        return ConversationHandler.END

# Cancel order
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        
        await update.message.reply_text(
            "Canceled. Type /start to begin again! 😊",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Clear user data
        context.user_data.clear()
        
        # Remove saved state from database
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to clear user state from DB: {e}")
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
        log_error(update.effective_user.id, e, "cancel")
        return ConversationHandler.END

# Main function to run the bot
def main() -> None:
    try:
        # Initialize the database
        init_db()
        
        # Create the application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Set up the conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_category)],
                ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_item)],
                CART: [MessageHandler(filters.TEXT & ~filters.COMMAND, cart_action)],
                REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_item)],
                DELIVERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_delivery)],
                ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                TABLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_table)],
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
                CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_order)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            persistent=True,
            name="conversation_handler"
        )
        
        # Add handlers to application
        application.add_handler(conv_handler)
        application.add_handler(CallbackQueryHandler(handle_button))
        application.add_handler(CommandHandler("orders", orders))
        
        # Run the bot
        logger.info("Bot started.")
        application.run_polling()
    except Exception as e:
        logger.error(f"Error in main: {e}")
        log_error(0, e, "main")
        raise

if __name__ == "__main__":
    main()
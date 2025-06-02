# Importing necessary libraries for the bot
import logging
import json
import re
import sqlite3
import os  # Добавляем для чтения переменных окружения
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
        logging.StreamHandler()  # Вывод в stdout
    ]
)
logger = logging.getLogger(__name__)

# Bot token and admin IDs
BOT_TOKEN = os.getenv("BOT_TOKEN")
logger.info(f"BOT_TOKEN value: {BOT_TOKEN}")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set, exiting...")
    exit(1)
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

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect("/data/orders.db")  # Используем путь к диску Render
        cursor = conn.cursor()
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
        conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    finally:
        conn.close()

# Save order to SQLite
def save_to_db(order):
    try:
        conn = sqlite3.connect("/data/orders.db")  # Используем путь к диску Render
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
    finally:
        conn.close()

# Get recent orders from SQLite (last 5)
def get_recent_orders():
    try:
        conn = sqlite3.connect("/data/orders.db")  # Используем путь к диску Render
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 5")
        orders = cursor.fetchall()
        return orders
    except Exception as e:
        logger.error(f"Failed to get recent orders: {e}")
        return []
    finally:
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
            logger.info("No orders found for /orders command.")
            return

        # Format the orders for display
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
        await update.message.reply_text("Something went wrong while fetching orders. Please try again! 😊")

# Command /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = update.effective_user.id
        logger.info(f"Received /start from user {user_id}")
        # Initialize the cart and previous state
        context.user_data["cart"] = []
        context.user_data["previous_state"] = None
        # Show menu categories with the cafe address
        keyboard = [[category] for category in MENU.keys()]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        await update.message.reply_text(
            f"Hello! 😊 Welcome to One Shot Cafe!\nWe are located at: {CAFE_ADDRESS}\nChoose a category:",
            reply_markup=reply_markup
        )
        logger.info(f"Sent welcome message to user {user_id}")
        return CATEGORY
    except Exception as e:
        logger.error(f"Error in start for user {user_id}: {e}")
        await update.message.reply_text("Something went wrong. Please try again later! 😊")
        return ConversationHandler.END

# Select category
async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        category = update.message.text
        if category == "Back":
            # No previous state at CATEGORY, so just restart
            return await start(update, context)
        
        if category not in MENU:
            await update.message.reply_text("Oops, please choose a category from the list! 😊")
            return CATEGORY
        
        context.user_data["category"] = category
        context.user_data["previous_state"] = CATEGORY
        # Create a numbered list of drinks
        items = MENU[category]
        items_list = "\n".join([f"{i+1}. {item['name']} — {item['price']} $" for i, item in enumerate(items)])
        # Create buttons (3 per row)
        keyboard = []
        row = []
        for item in items:
            row.append(item['name'])
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        # Add Back button
        keyboard.append(["Back"])
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        # Send message with a nice list and buttons
        await update.message.reply_text(
            f"Choose a drink from the category {category}:\n\n{items_list}\n\nTap on the drink name below:",
            reply_markup=reply_markup
        )
        return ITEM
    except Exception as e:
        logger.error(f"Error in select_category: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return CATEGORY

# Select drink
async def select_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        selected_item = update.message.text
        if selected_item == "Back":
            # Go back to CATEGORY
            return await start(update, context)

        category = context.user_data["category"]
        items = MENU[category]
        item = next((i for i in items if i["name"] == selected_item), None)
        if not item:
            await update.message.reply_text("Please choose a drink from the list! 😊")
            return ITEM
        
        # Add the selected drink to the cart
        context.user_data["cart"].append({"name": item["name"], "price": item["price"]})
        context.user_data["previous_state"] = ITEM
        # Show the cart and ask what to do next
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in context.user_data["cart"]])
        total_price = sum(drink["price"] for drink in context.user_data["cart"])
        await update.message.reply_text(
            f"Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
            reply_markup=ReplyKeyboardMarkup(
                [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                one_time_keyboard=True
            )
        )
        return CART
    except Exception as e:
        logger.error(f"Error in select_item: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return ITEM

# Cart actions
async def cart_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        action = update.message.text
        if action == "Back":
            # Go back to ITEM
            category = context.user_data["category"]
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
            return ITEM

        if action == "Add More Drinks":
            # Go back to category selection
            context.user_data["previous_state"] = CART
            keyboard = [[category] for category in MENU.keys()]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            await update.message.reply_text(
                "Choose another category:",
                reply_markup=reply_markup
            )
            return CATEGORY
        elif action == "Remove a Drink":
            # Show the cart and ask which drink to remove
            cart = context.user_data["cart"]
            if not cart:
                await update.message.reply_text("Your cart is empty! Let's add some drinks.")
                return CATEGORY
            context.user_data["previous_state"] = CART
            keyboard = [[drink["name"] for drink in cart]] + [["Back to Cart"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
            await update.message.reply_text(
                f"Your cart:\n{cart_summary}\n\nWhich drink would you like to remove?",
                reply_markup=reply_markup
            )
            return REMOVE
        elif action == "Place Order":
            # Proceed to delivery/pickup/on-site
            if not context.user_data["cart"]:
                await update.message.reply_text("Your cart is empty! Let's add some drinks.")
                return CATEGORY
            context.user_data["previous_state"] = CART
            keyboard = [["Delivery"], ["Pickup"], ["Drink On-Site"], ["Back"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            await update.message.reply_text("How would you like to receive your order?", reply_markup=reply_markup)
            return DELIVERY
        else:
            await update.message.reply_text("Please choose an option!")
            return CART
    except Exception as e:
        logger.error(f"Error in cart_action: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return CART

# Remove a drink from the cart
async def remove_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        selection = update.message.text
        if selection == "Back to Cart":
            # Return to cart actions
            cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in context.user_data["cart"]])
            total_price = sum(drink["price"] for drink in context.user_data["cart"])
            await update.message.reply_text(
                f"Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                    one_time_keyboard=True
                )
            )
            return CART
        # Remove the selected drink
        context.user_data["cart"] = [drink for drink in context.user_data["cart"] if drink["name"] != selection]
        # Show the updated cart using the modified cart
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in context.user_data["cart"]])
        total_price = sum(drink["price"] for drink in context.user_data["cart"])
        await update.message.reply_text(
            f"Drink removed! Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
            reply_markup=ReplyKeyboardMarkup(
                [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                one_time_keyboard=True
            )
        )
        return CART
    except Exception as e:
        logger.error(f"Error in remove_item: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return REMOVE

# Select delivery, pickup, or drink on-site
async def select_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        delivery = update.message.text
        if delivery == "Back":
            # Go back to CART
            cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in context.user_data["cart"]])
            total_price = sum(drink["price"] for drink in context.user_data["cart"])
            await update.message.reply_text(
                f"Your cart:\n{cart_summary}\nTotal: {total_price:.2f} $\n\nWhat would you like to do next?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Add More Drinks", "Remove a Drink"], ["Place Order"], ["Back"]],
                    one_time_keyboard=True
                )
            )
            return CART

        if delivery not in ["Delivery", "Pickup", "Drink On-Site"]:
            await update.message.reply_text("Choose 'Delivery', 'Pickup', or 'Drink On-Site'! 😊")
            return DELIVERY
        context.user_data["delivery"] = delivery
        context.user_data["previous_state"] = DELIVERY
        if delivery == "Delivery":
            await update.message.reply_text("Enter your delivery address:", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
            return ADDRESS
        else:
            await update.message.reply_text("Enter your name:", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
            return NAME
    except Exception as e:
        logger.error(f"Error in select_delivery: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return DELIVERY

# Enter address (for delivery only)
async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        address = update.message.text
        if address == "Back":
            # Go back to DELIVERY
            keyboard = [["Delivery"], ["Pickup"], ["Drink On-Site"], ["Back"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            await update.message.reply_text("How would you like to receive your order?", reply_markup=reply_markup)
            return DELIVERY
        context.user_data["address"] = address
        context.user_data["previous_state"] = ADDRESS
        await update.message.reply_text("Enter your name:", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
        return NAME
    except Exception as e:
        logger.error(f"Error in get_address: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return ADDRESS

# Enter name
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        name = update.message.text
        if name == "Back":
            # Go back to the previous state
            previous_state = context.user_data.get("previous_state")
            if previous_state == DELIVERY:
                keyboard = [["Delivery"], ["Pickup"], ["Drink On-Site"], ["Back"]]
                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
                await update.message.reply_text("How would you like to receive your order?", reply_markup=reply_markup)
                return DELIVERY
            elif previous_state == ADDRESS:
                await update.message.reply_text("Enter your delivery address:", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
                return ADDRESS
            else:
                # Default to DELIVERY if something goes wrong
                keyboard = [["Delivery"], ["Pickup"], ["Drink On-Site"], ["Back"]]
                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
                await update.message.reply_text("How would you like to receive your order?", reply_markup=reply_markup)
                return DELIVERY

        context.user_data["name"] = name
        context.user_data["previous_state"] = NAME
        if context.user_data["delivery"] == "Drink On-Site":
            await update.message.reply_text("Enter your table number:", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
            return TABLE
        await update.message.reply_text("Enter your phone number (e.g., +1234567890):", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
        return PHONE
    except Exception as e:
        logger.error(f"Error in get_name: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return NAME

# Enter table number (for on-site orders)
async def get_table(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        table = update.message.text
        if table == "Back":
            # Go back to NAME
            await update.message.reply_text("Enter your name:", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
            return NAME

        # Validate table number (must be a number between 1 and 20)
        try:
            table_num = int(table)
            if not 1 <= table_num <= 20:
                await update.message.reply_text("Please enter a table number between 1 and 20!")
                return TABLE
        except ValueError:
            await update.message.reply_text("Please enter a valid table number (e.g., 5)!")
            return TABLE
        context.user_data["table"] = table
        context.user_data["previous_state"] = TABLE
        # Skip phone number for Drink On-Site and go straight to confirmation
        cart = context.user_data["cart"]
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
        total_price = sum(drink["price"] for drink in cart)
        order_summary = (
            f"Your order:\n"
            f"Drinks:\n{cart_summary}\n"
            f"Total: {total_price:.2f} $\n"
            f"Method: {context.user_data['delivery']}\n"
            f"Table Number: {context.user_data.get('table', 'Not specified')}\n"
            f"Name: {context.user_data['name']}\n"
            f"Everything correct? (Yes/No)"
        )
        keyboard = [["Yes"], ["No"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        await update.message.reply_text(order_summary, reply_markup=reply_markup)
        return CONFIRM
    except Exception as e:
        logger.error(f"Error in get_table: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return TABLE

# Enter phone number (for Delivery and Pickup only)
async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        phone = update.message.text
        if phone == "Back":
            # Go back to NAME
            await update.message.reply_text("Enter your name:", reply_markup=ReplyKeyboardMarkup([["Back"]], one_time_keyboard=True))
            return NAME

        # Validate phone number
        if not re.match(r"^\+?\d{10,15}$", phone):
            await update.message.reply_text("Oops, please enter a valid phone number (e.g., +1234567890)! 😊")
            return PHONE
        context.user_data["phone"] = phone
        context.user_data["previous_state"] = PHONE
        # Show order summary with all drinks
        cart = context.user_data["cart"]
        cart_summary = "\n".join([f"- {drink['name']} — {drink['price']} $" for drink in cart])
        total_price = sum(drink["price"] for drink in cart)
        order_summary = (
            f"Your order:\n"
            f"Drinks:\n{cart_summary}\n"
            f"Total: {total_price:.2f} $\n"
            f"Method: {context.user_data['delivery']}\n"
        )
        if context.user_data["delivery"] == "Delivery":
            order_summary += f"Address: {context.user_data.get('address', 'Not specified')}\n"
        elif context.user_data["delivery"] == "Drink On-Site":
            order_summary += f"Table Number: {context.user_data.get('table', 'Not specified')}\n"
        order_summary += (
            f"Name: {context.user_data['name']}\n"
            f"Phone: {context.user_data['phone']}\n"
            f"Everything correct? (Yes/No)"
        )
        keyboard = [["Yes"], ["No"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        await update.message.reply_text(order_summary, reply_markup=reply_markup)
        return CONFIRM
    except Exception as e:
        logger.error(f"Error in get_phone: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return PHONE

# Confirm order
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.message.text == "Yes":
            # Create order with all drinks
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
            # Save to SQLite
            save_to_db(order)
            # Notify admins via Telegram
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
            # Send notification to all admins
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=order_summary)
                    logger.info(f"Notification sent to admin {admin_id}.")
                except Exception as e:
                    logger.error(f"Failed to send notification to admin {admin_id}: {e}")
            # Confirm to user with the exact message
            confirmation_message = (
                f"Great! Your order is placed! Thank you! 😊\n"
                f"Please pick up your order at: {CAFE_ADDRESS}\n\n"
                f"To place another order, tap the button below or type /start!"
            )
            # Add inline button to restart
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("Place Another Order", callback_data="restart")]
            ])
            await update.message.reply_text(confirmation_message, reply_markup=reply_markup)
            # Clear the cart
            context.user_data["cart"] = []
            return ConversationHandler.END
        else:
            await update.message.reply_text("Order canceled. Type /start to begin again! 😊", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in confirm_order: {e}")
        await update.message.reply_text("Something went wrong. Please try again! 😊")
        return ConversationHandler.END

# Handle inline button clicks
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        if query.data == "restart":
            # Simulate /start command
            context.user_data["cart"] = []
            keyboard = [[category] for category in MENU.keys()]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            await query.message.reply_text(
                f"Hello! 😊 Welcome to One Shot Cafe!\nWe are located at: {CAFE_ADDRESS}\nChoose a category:",
                reply_markup=reply_markup
            )
            logger.info(f"User {query.from_user.id} restarted the order process.")
            return CATEGORY
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in handle_button: {e}")
        return ConversationHandler.END

# Cancel order
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.reply_text("Canceled. Type /start to begin again! 😊", reply_markup=ReplyKeyboardRemove())
        logger.info(f"User {update.effective_user.id} canceled the order.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
        return ConversationHandler.END

# Main function to run the bot
if __name__ == "__main__":
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
        )
        # Add handlers to application
        application.add_handler(conv_handler)
        application.add_handler(CallbackQueryHandler(handle_button))
        application.add_handler(CommandHandler("orders", orders))
        # Start the bot
        logger.info("Bot started.")
        application.run_polling()
    except Exception as e:
        logger.error(f"Error in main: {e}")
        raise
    
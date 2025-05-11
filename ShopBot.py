import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from collections import Counter
import asyncio

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_carts = {}
ticket_receipts = {}
user_tickets = {}  # Track existing ticket channels per user

SERVER_FILES = {
    '2b2t': '2b2t_inventory.json',
    'constantiam': 'constantiam_inventory.json'
}

CATEGORY_COLORS = {
    'electronics': discord.ButtonStyle.primary,
    'clothing': discord.ButtonStyle.success,
    'food': discord.ButtonStyle.danger,
    'accessories': discord.ButtonStyle.secondary,
    'miscellaneous': discord.ButtonStyle.green,
}



class AddItemModal(discord.ui.Modal, title="Add New Item"):
    def __init__(self, server):
        super().__init__()
        self.server_value = server

        self.category = discord.ui.TextInput(label="Category", placeholder="Enter category")
        self.item_name = discord.ui.TextInput(label="Item Name", placeholder="Enter item name")
        self.price = discord.ui.TextInput(label="Price", placeholder="e.g., 1.5")
        self.stock = discord.ui.TextInput(label="Stock", placeholder="e.g., 100")
        self.image_url = discord.ui.TextInput(
            label="Image URL (optional)", placeholder="Direct image link", required=False
        )

        self.add_item(self.category)
        self.add_item(self.item_name)
        self.add_item(self.price)
        self.add_item(self.stock)
        self.add_item(self.image_url)

    async def on_submit(self, interaction: discord.Interaction):
        server = self.server_value
        filename = SERVER_FILES.get(server)

        if not filename:
            await interaction.response.send_message("Error: Invalid server selected.", ephemeral=True)
            return

        if os.path.exists(filename):
            with open(filename, "r") as f:
                inventory = json.load(f)
        else:
            inventory = {}

        try:
            price = float(self.price.value.strip())
            stock = int(self.stock.value.strip())
        except ValueError:
            await interaction.response.send_message("Invalid price or stock value.", ephemeral=True)
            return

        category = self.category.value.strip()
        item = self.item_name.value.strip()
        image = self.image_url.value.strip()

        if category not in inventory:
            inventory[category] = {}
        inventory[category][item] = {
            "price": price,
            "stock": stock,
            "image": image
        }

        with open(filename, "w") as f:
            json.dump(inventory, f, indent=2)

        await interaction.response.send_message(
            f"✅ **{item}** has been added to **{server.title()}** under **{category}**!", ephemeral=True
        )





class AdditemServerSelect(discord.ui.Select):
    def __init__(self, user_id: int):
        self.user_id = user_id
        options = [
            discord.SelectOption(label="2b2t", value="2b2t"),
            discord.SelectOption(label="Constantiam", value="constantiam")
        ]
        super().__init__(placeholder="Select the server", options=options, custom_id="server_select")

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot interact with this menu.", ephemeral=True)
            return

        server = self.values[0]
        await interaction.response.send_modal(AddItemModal(server))

class AdditemServerSelectView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(AdditemServerSelect(user_id))


class ServerSelectView(discord.ui.View):
    def __init__(self, user_id: int = 0):  # 0 = public
        super().__init__(timeout=None)
        for srv in SERVER_FILES.keys():
            self.add_item(ServerButton(user_id, srv))


#REMOVE
class RemoveServerSelect(discord.ui.Select):
    def __init__(self, user_id: int):
        self.user_id = user_id
        options = [
            discord.SelectOption(label="2b2t", value="2b2t"),
            discord.SelectOption(label="Constantiam", value="constantiam")
        ]
        super().__init__(placeholder="Select server", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot interact with this menu.", ephemeral=True)
            return

        server = self.values[0]
        inventory = load_inventory(server)

        if not inventory:
            await interaction.response.send_message("⚠️ No items found in this server.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"📂 Select a category in **{server.title()}**:",
            view=RemoveCategorySelectView(self.user_id, server, list(inventory.keys())),
            ephemeral=True
        )


class RemoveServerSelectView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(RemoveServerSelect(user_id))


class RemoveCategorySelect(discord.ui.Select):
    def __init__(self, user_id: int, server: str, categories: list):
        self.user_id = user_id
        self.server = server
        options = [discord.SelectOption(label=cat, value=cat) for cat in categories]
        super().__init__(placeholder="Select category", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Unauthorized", ephemeral=True)
            return

        category = self.values[0]
        inventory = load_inventory(self.server)
        items = inventory.get(category, {}).keys()

        if not items:
            await interaction.response.send_message("⚠️ No items in this category.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"🧾 Select an item to remove from **{category}**:",
            view=RemoveItemSelectView(self.user_id, self.server, category, list(items)),
            ephemeral=True
        )


class RemoveCategorySelectView(discord.ui.View):
    def __init__(self, user_id: int, server: str, categories: list):
        super().__init__(timeout=None)
        self.add_item(RemoveCategorySelect(user_id, server, categories))


class RemoveItemSelect(discord.ui.Select):
    def __init__(self, user_id: int, server: str, category: str, items: list):
        self.user_id = user_id
        self.server = server
        self.category = category
        options = [discord.SelectOption(label=item, value=item) for item in items]
        super().__init__(placeholder="Select item to delete", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Unauthorized", ephemeral=True)
            return

        item = self.values[0]
        inventory = load_inventory(self.server)

        if self.category in inventory and item in inventory[self.category]:
            del inventory[self.category][item]
            if not inventory[self.category]:
                del inventory[self.category]  # clean empty category
            save_inventory(self.server, inventory)

            await interaction.response.send_message(
                f"🗑️ Deleted **{item}** from **{self.category}** in **{self.server.title()}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⚠️ Could not find the item to delete.",
                ephemeral=True
            )


class RemoveItemSelectView(discord.ui.View):
    def __init__(self, user_id: int, server: str, category: str, items: list):
        super().__init__(timeout=None)
        self.add_item(RemoveItemSelect(user_id, server, category, items))

#COMMANDS
@bot.tree.command(name="additem", description="Add a new item to the inventory")
@app_commands.checks.has_permissions(administrator=True)
async def additem(interaction: discord.Interaction):
    view = AdditemServerSelectView(interaction.user.id)
    await interaction.response.send_message("Please select a server:", view=view, ephemeral=True)

@bot.tree.command(name="removeitem", description="Remove an item from the inventory")
@app_commands.checks.has_permissions(administrator=True)
async def removeitem(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🗑️ Select a server to remove an item from:", 
        view=RemoveServerSelectView(interaction.user.id),
        ephemeral=True
    )



@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    synced = await bot.tree.sync()
    print(f"✅ Synced {len(synced)} commands")

    for guild in bot.guilds:
        try:
            channel_name = "shop"
            shop_channel = discord.utils.get(guild.text_channels, name=channel_name)

            if not shop_channel:
                # Create the channel if it doesn't exist
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                }

                shop_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
                print(f"✅ Created #{channel_name} in {guild.name}")
            else:
                print(f"ℹ️ Found existing #{channel_name} in {guild.name}")

            # Ensure bot can send messages in the channel
            test_msg = await shop_channel.send("⏳ Initializing shop...")
            await test_msg.delete()

            # (Optional) clear previous bot messages
            async for msg in shop_channel.history(limit=50):
                if msg.author == bot.user:
                    await msg.delete()

            # Send fresh UI message
            await shop_channel.send(
                "👋 Welcome to the shop! Please select a server to start:",
                view=ServerSelectView(user_id=0)
            )
            print(f"✅ Posted UI in #{channel_name} for {guild.name}")

        except discord.Forbidden:
            print(f"❌ Missing permissions to send message in #{channel_name} for {guild.name}")
        except discord.HTTPException as e:
            print(f"❌ Failed to send message in {guild.name}: {e}")
        except Exception as e:
            print(f"⚠️ Unexpected error in {guild.name}: {e}")






def setup(bot):
    bot.add_cog(Inventory(bot))


def load_inventory(server: str) -> dict:
    filename = SERVER_FILES.get(server.lower())
    if not filename:
        return {}
    if not os.path.isfile(filename):
        with open(filename, 'w') as f:
            json.dump({}, f, indent=4)
    with open(filename, 'r') as f:
        return json.load(f)

def save_inventory(server: str, data: dict):
    filename = SERVER_FILES.get(server.lower())
    if not filename:
        return
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

class ServerSelectView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        for srv in SERVER_FILES.keys():
            self.add_item(ServerButton(user_id, srv))

class ServerButton(discord.ui.Button):
    def __init__(self, user_id: int, server_name: str):
        super().__init__(label=server_name.title(), style=discord.ButtonStyle.primary)
        self.user_id = user_id
        self.server_name = server_name.lower()

    async def callback(self, interaction: discord.Interaction):
        if self.user_id != 0 and interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot use this.", ephemeral=True)
            return

        # Continue with your ticket creation logic as before
        guild = interaction.guild
        member = interaction.user

        existing_channel = user_tickets.get(member.id)
        if existing_channel:
            ticket_ch = guild.get_channel(existing_channel)
            if ticket_ch:
                await interaction.response.send_message(
                    f"📨 You already have a ticket: {ticket_ch.mention}", ephemeral=True
                )
                return
            else:
                user_tickets.pop(member.id, None)

        ticket_name = f"{self.server_name}-shop-{member.name}".lower().replace(" ", "-")
        ticket_ch = await guild.create_text_channel(
            ticket_name,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            },
            topic=f"Private shop channel for {member.name} on {self.server_name}"
        )

        user_tickets[member.id] = ticket_ch.id
        user_carts[member.id] = {'server': self.server_name, 'items': []}

        await ticket_ch.send(
            f"👋 Welcome {member.mention}! You are now shopping in **{self.server_name.title()}**.",
            view=HomeView(member.id)
        )

        await interaction.response.send_message(
            f"✅ Your private shop channel has been created: {ticket_ch.mention}",
            ephemeral=True
        )

class HomeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(ViewItemsButton(user_id))
        self.add_item(ViewCartButton(user_id))
        self.add_item(ConfirmOrderButton(user_id))

class ViewItemsButton(discord.ui.Button):
    def __init__(self, user_id: int):
        super().__init__(label="🛍️ View Items", style=discord.ButtonStyle.primary)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        cart = user_carts.get(self.user_id)
        if not cart or not cart.get('server'):
            await interaction.response.send_message("❌ Please select a server first with `/shop`.", ephemeral=True)
            return
        server = cart['server']
        inventory = load_inventory(server)
        if not inventory:
            await interaction.response.send_message("❌ No items in this shop yet.", ephemeral=True)
            return
        await interaction.response.send_message(
            "📂 **Select a category:**", view=CategoryListView(self.user_id, server)
        )

class CategoryListView(discord.ui.View):
    def __init__(self, user_id: int, server: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.server = server

        categories = sorted(load_inventory(server).keys())  # sort alphabetically

        for category in categories:
            style = CATEGORY_COLORS.get(category.lower(), discord.ButtonStyle.secondary)
            self.add_item(CategoryButton(user_id, server, category, style))

        self.add_item(BackToHomeButton(user_id))



class CategoryButton(discord.ui.Button):
    def __init__(self, user_id: int, server: str, category: str, style):
        super().__init__(label=f"{category.title()}", style=discord.ButtonStyle.primary)
        self.user_id = user_id
        self.server = server
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot access this button.", ephemeral=True)
            return

        items = load_inventory(self.server).get(self.category, {})

        # ✅ Filter out items with stock <= 0
        available_items = {
            item_name: info for item_name, info in items.items()
            if info.get("stock", 0) > 0
        }

        if not available_items:
            await interaction.response.send_message("❌ No available items in this category.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        for item_name, info in available_items.items():
            embed = discord.Embed(
                title=item_name,
                description=f"💲 ${info['price']:.2f}\n📦 Stock: {info['stock']}",
                color=discord.Color.blue()
            )
            if info.get('image'):
                embed.set_image(url=info['image'])

            view = discord.ui.View(timeout=None)
            view.add_item(AddToCartButton(self.user_id, item_name, self.category))

            await interaction.channel.send(embed=embed, view=view)
            await asyncio.sleep(0.1)

        await interaction.channel.send("🏠 Back to home:", view=HomeView(self.user_id))





class BackToHomeButton(discord.ui.Button):
    def __init__(self, user_id: int):
        super().__init__(label="🔙 Back", style=discord.ButtonStyle.danger)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot use this button.", ephemeral=True)
            return

        await interaction.response.edit_message(
            content="🏠 Back to home:",
            view=HomeView(self.user_id)
        )


class AddToCartButton(discord.ui.Button):
    def __init__(self, user_id: int, item_name: str, category: str):
        super().__init__(label="Add to Cart", style=discord.ButtonStyle.success)
        self.user_id = user_id
        self.item_name = item_name
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        cart = user_carts.setdefault(self.user_id, {'server': None, 'items': []})
        cart['items'].append({'name': self.item_name, 'category': self.category})
        await interaction.response.send_message(f"✅ **{self.item_name}** added to your cart.", ephemeral=True)

class ViewCartButton(discord.ui.Button):
    def __init__(self, user_id: int):
        super().__init__(label="🛒 View Cart", style=discord.ButtonStyle.secondary)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        cart = user_carts.get(self.user_id, {})
        items = cart.get('items', [])
        if not items:
            await interaction.response.send_message("🛒 Your cart is empty.", ephemeral=True)
            return

        server = cart.get('server')
        inventory = load_inventory(server)
        counts = Counter((item['name'], item['category']) for item in items)
        desc = ""
        total = 0.0

        for (name, category), cnt in counts.items():
            if category in inventory and name in inventory[category]:
                price = inventory[category][name]['price']
                total += price * cnt
                desc += f"**{name}** (in {category}) x{cnt} @ ${price:.2f}\n"
            else:
                desc += f"⚠️ **{name}** (in {category}) no longer exists\n"

        desc += f"\n💰 **Total: ${total:.2f}**"
        embed = discord.Embed(title="🛒 Your Cart", description=desc, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)


class CloseTicketView(discord.ui.View):
    def __init__(self, ticket_channel_id: int):
        super().__init__(timeout=None)
        self.ticket_channel_id = ticket_channel_id
        self.add_item(CloseTicketButton(ticket_channel_id))

class CloseTicketButton(discord.ui.Button):
    def __init__(self, ticket_channel_id: int):
        super().__init__(label="🔒 Close Ticket", style=discord.ButtonStyle.danger)
        self.ticket_channel_id = ticket_channel_id

    async def callback(self, interaction: discord.Interaction):
        log_channel = discord.utils.get(interaction.guild.text_channels, name="ticket-logs")
        if not log_channel:
            await interaction.response.send_message("⚠️ No 'ticket-logs' channel found.", ephemeral=True)
            return

        # Get all messages in the ticket channel
        ticket_channel = interaction.channel
        messages = [msg async for msg in ticket_channel.history(limit=None, oldest_first=True)]
        
        # Build a log of the chat
        log_text = f"📝 **Transcript for {ticket_channel.name}**\n\n"
        for msg in messages:
            timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M')
            log_text += f"[{timestamp}] {msg.author}: {msg.content}\n"

        # If the log is too long, send it as a file
        if len(log_text) > 1900:
            with open("ticket_log.txt", "w", encoding="utf-8") as f:
                f.write(log_text)
            await log_channel.send(
                content=f"📁 Log for {ticket_channel.name}:",
                embed=ticket_receipts.get(ticket_channel.id),
                file=discord.File("ticket_log.txt")
            )
            os.remove("ticket_log.txt")
        else:
            await log_channel.send(
                content=f"📄 Log for {ticket_channel.name}:\n{log_text}",
                embed=ticket_receipts.get(ticket_channel.id)
            )

        await interaction.response.send_message("✅ Ticket will be closed.", ephemeral=True)
        await ticket_channel.delete()



class ConfirmOrderButton(discord.ui.Button):
    def __init__(self, user_id: int):
        super().__init__(label="✅ Confirm Order", style=discord.ButtonStyle.success)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        cart = user_carts.get(self.user_id)
        if not cart or not cart.get('items') or not cart.get('server'):
            await interaction.response.send_message("🛒 Nothing to confirm.", ephemeral=True)
            return

        items = cart['items']
        server = cart['server']
        inventory = load_inventory(server)
        counts = Counter((item['name'], item['category']) for item in items)
        lines = []
        total = 0.0

        for (name, category), cnt in counts.items():
            if category in inventory and name in inventory[category]:
                price = float(inventory[category][name]['price'])
                total += price * cnt
                lines.append(f"{cnt}x {name} @ ${price:.2f}")
            else:
                await interaction.response.send_message(
                    f"⚠️ Item `{name}` in category `{category}` no longer exists in the inventory.",
                    ephemeral=True
                )
                return

        if total < 5.0:
            await interaction.response.send_message(
                f"⚠️ The minimum order is $5.00. Your cart total is ${total:.2f}.",
                ephemeral=True
            )
            return

        member = interaction.guild.get_member(self.user_id)
        ticket_name = f"{server}-ticket-{member.name}".lower().replace(" ", "-")

        ticket_ch = await interaction.guild.create_text_channel(
            ticket_name,
            overwrites={
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            },
            topic=f"Order ticket for {member.name} on {server}"
        )

        receipt_text = "\n".join(lines) + f"\n\n💰 **Total: ${total:.2f}**"
        embed = discord.Embed(
            title="🧾 Order Receipt",
            description=f"**User:** {member.mention}\n**Server:** {server.title()}\n\n{receipt_text}",
            color=discord.Color.green()
        )

        await ticket_ch.send(
            f"New order from {member.mention}:",
            embed=embed,
            view=CloseTicketView(ticket_ch.id)
        )

        ticket_receipts[ticket_ch.id] = embed
        user_carts[self.user_id]['items'] = []

        try:
            user_channel = interaction.channel
            await interaction.response.send_message(
                f"✅ Ticket created: {ticket_ch.mention}\n🗑️ Closing your shop chat...",
                ephemeral=True
            )
            await user_channel.delete()
        except Exception as e:
            await ticket_ch.send(f"⚠️ Failed to delete the shop channel: {e}")


@bot.tree.command(name="shop", description="Start browsing the shop")
async def shop_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    existing_channel_id = user_tickets.get(user_id)
    current_channel = interaction.channel

    if existing_channel_id:
        existing_channel = interaction.guild.get_channel(existing_channel_id)
        if existing_channel:
            if current_channel.id == existing_channel.id:
                # They're already in their shop channel, show Home UI
                await interaction.response.send_message("🏠 You're in your shop already!", view=HomeView(user_id), ephemeral=True)
            else:
                # They're somewhere else, direct them to the correct place
                await interaction.response.send_message(
                    f"📨 You already have a shop open here: {existing_channel.mention}",
                    ephemeral=True
                )
            return
        else:
            user_tickets.pop(user_id, None)

    # No existing ticket — show server select view
    await interaction.response.send_message(
        "🌐 Select your server:", view=ServerSelectView(user_id), ephemeral=True
    )



class EditItemCategorySelect(discord.ui.Select):
    def __init__(self, user_id: int, server: str):
        self.user_id = user_id
        self.server = server
        inventory = load_inventory(server)
        options = [discord.SelectOption(label=cat, value=cat) for cat in inventory.keys()]
        super().__init__(placeholder="Select a category", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Unauthorized", ephemeral=True)
            return

        category = self.values[0]
        inventory = load_inventory(self.server)
        items = list(inventory.get(category, {}).keys())

        if not items:
            await interaction.response.send_message("⚠️ No items in this category.", ephemeral=True)
            return

        await interaction.response.send_message(
            "✏️ Select an item to edit:",
            view=EditItemNameSelectView(self.user_id, self.server, category, items),
            ephemeral=True
        )


class EditItemCategorySelectView(discord.ui.View):
    def __init__(self, user_id: int, server: str):
        super().__init__(timeout=None)
        self.add_item(EditItemCategorySelect(user_id, server))


class EditItemNameSelect(discord.ui.Select):
    def __init__(self, user_id: int, server: str, category: str, items: list):
        self.user_id = user_id
        self.server = server
        self.category = category
        options = [discord.SelectOption(label=item, value=item) for item in items]
        super().__init__(placeholder="Select item to edit", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Unauthorized", ephemeral=True)
            return

        item_name = self.values[0]
        await interaction.response.send_modal(EditItemModal(self.server, self.category, item_name))


class EditItemNameSelectView(discord.ui.View):
    def __init__(self, user_id: int, server: str, category: str, items: list):
        super().__init__(timeout=None)
        self.add_item(EditItemNameSelect(user_id, server, category, items))


class EditItemModal(discord.ui.Modal, title="Edit Item"):
    def __init__(self, server: str, category: str, item_name: str):
        super().__init__()
        self.server = server
        self.category = category
        self.item_name = item_name

        inventory = load_inventory(server)
        item = inventory[category][item_name]

        self.new_name = discord.ui.TextInput(label="Item Name", default=item_name)
        self.price = discord.ui.TextInput(label="Price", default=str(item['price']))
        self.stock = discord.ui.TextInput(label="Stock", default=str(item['stock']))
        self.image = discord.ui.TextInput(label="Image URL", default=item.get('image', ''), required=False)

        self.add_item(self.new_name)
        self.add_item(self.price)
        self.add_item(self.stock)
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_price = float(self.price.value.strip())
            new_stock = int(self.stock.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid price or stock.", ephemeral=True)
            return

        inventory = load_inventory(self.server)

        # Delete old item name if changed
        if self.item_name != self.new_name.value.strip():
            del inventory[self.category][self.item_name]

        inventory[self.category][self.new_name.value.strip()] = {
            "price": new_price,
            "stock": new_stock,
            "image": self.image.value.strip()
        }

        save_inventory(self.server, inventory)

        await interaction.response.send_message(
            f"✅ **{self.new_name.value.strip()}** has been updated.", ephemeral=True
        )


@bot.tree.command(name="edititem", description="Edit an existing item")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(server="Server to edit item in")
async def edititem(interaction: discord.Interaction, server: str):
    if server.lower() not in SERVER_FILES:
        await interaction.response.send_message("❌ Invalid server name.", ephemeral=True)
        return

    await interaction.response.send_message(
        "📂 Select a category:",
        view=EditItemCategorySelectView(interaction.user.id, server.lower()),
        ephemeral=True
    )

# Add load_inventory and save_inventory if not already present:
def load_inventory(server: str) -> dict:
    filename = SERVER_FILES.get(server.lower())
    if not filename:
        return {}
    if not os.path.isfile(filename):
        with open(filename, 'w') as f:
            json.dump({}, f, indent=4)
    with open(filename, 'r') as f:
        return json.load(f)

def save_inventory(server: str, data: dict):
    filename = SERVER_FILES.get(server.lower())
    if not filename:
        return
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)


class DeleteItemView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        for srv in SERVER_FILES.keys():
            self.add_item(DeleteServerButton(user_id, srv))

class DeleteServerButton(discord.ui.Button):
    def __init__(self, user_id: int, server_name: str):
        super().__init__(label=server_name.title(), style=discord.ButtonStyle.danger)
        self.user_id = user_id
        self.server = server_name.lower()

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You can't use this.", ephemeral=True)
            return

        inventory = load_inventory(self.server)
        if not inventory:
            await interaction.response.send_message("⚠️ No inventory found.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"📂 Choose a category in **{self.server.title()}**:",
            view=DeleteCategoryView(self.user_id, self.server),
            ephemeral=True
        )

class DeleteCategoryView(discord.ui.View):
    def __init__(self, user_id: int, server: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.server = server
        categories = sorted(load_inventory(server).keys())
        self.add_item(DeleteCategoryDropdown(user_id, server, categories))

class DeleteCategoryDropdown(discord.ui.Select):
    def __init__(self, user_id: int, server: str, categories: list):
        self.user_id = user_id
        self.server = server
        options = [discord.SelectOption(label=cat, value=cat) for cat in categories]
        super().__init__(placeholder="Select category", options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        inventory = load_inventory(self.server)
        items = inventory.get(category, {}).keys()
        if not items:
            await interaction.response.send_message("⚠️ No items in this category.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"🧾 Select an item to delete from **{category}**:",
            view=DeleteItemDropdownView(self.user_id, self.server, category, list(items)),
            ephemeral=True
        )

class DeleteItemDropdownView(discord.ui.View):
    def __init__(self, user_id: int, server: str, category: str, items: list):
        super().__init__(timeout=None)
        self.add_item(DeleteItemDropdown(user_id, server, category, items))

class DeleteItemDropdown(discord.ui.Select):
    def __init__(self, user_id: int, server: str, category: str, items: list):
        self.user_id = user_id
        self.server = server
        self.category = category
        options = [discord.SelectOption(label=item, value=item) for item in items]
        super().__init__(placeholder="Select item to delete", options=options)

    async def callback(self, interaction: discord.Interaction):
        item = self.values[0]
        inventory = load_inventory(self.server)

        if item in inventory.get(self.category, {}):
            del inventory[self.category][item]
            if not inventory[self.category]:
                del inventory[self.category]  # Remove empty category
            save_inventory(self.server, inventory)

            await interaction.response.send_message(
                f"🗑️ Deleted **{item}** from **{self.category}** in **{self.server.title()}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Could not find the item to delete.",
                ephemeral=True
            )

@app_commands.command(name="deleteitem", description="Delete an item from the inventory")
@app_commands.checks.has_permissions(administrator=True)
async def delete_item(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🗑️ Select a server to delete an item from:",
        view=DeleteItemView(interaction.user.id),
        ephemeral=True
    )





bot.run("TOKEN")




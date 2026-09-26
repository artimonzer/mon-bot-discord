import asyncio
import os
from collections import defaultdict, deque
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.moderation = True
intents.invites = True
intents.voice_states = True

# Désactivation de la commande help par défaut de discord.py
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --- CONFIGURATION ---
SALON_LOGS_MOD = 1529826221255299073
SALON_BIENVENUE_ID = 1529636643777024070
SALON_DEPART_ID = 1529637614582239323
ROLE_MUTE_ID = 1529827552540098710
ROLE_JAIL_ID = 1529827786410430627
ROLE_AUTO_ID = 1531708597501821119
CATEGORIE_TICKET_ID = 1529639229838196817

# Liste des rôles autorisés (incluant tes deux nouveaux ID)
ROLES_AUTORISES = {1528983405205786714, 1529644667938017321, 1529641074518397138, 1529639915711627384}

deleted_messages_cache = defaultdict(lambda: deque(maxlen=25))
spam_cooldowns = defaultdict(deque)
action_logs = defaultdict(list)
admin_logs = defaultdict(list)
active_spam_tasks = {}

def est_admin_ctx(ctx):
    return any(role.id in ROLES_AUTORISES for role in ctx.author.roles)

def est_admin_interaction(interaction: discord.Interaction):
    return any(role.id in ROLES_AUTORISES for role in interaction.user.roles)

def enregistrer_action(member_id: int, type_action: str, admin: str, raison: str):
    details = {
        "type": type_action,
        "admin": admin,
        "time": datetime.now().strftime("%d/%m/%Y à %H:%M"),
        "raison": raison,
    }
    action_logs[member_id].append(details)
    admin_logs[admin].append(details)

async def envoyer_log_salon(guild, member, titre, raison, mod_name, mp=None, ref="s_6CAG4", couleur=discord.Color.green()):
    channel = guild.get_channel(SALON_LOGS_MOD)
    if not channel:
        return
    embed = discord.Embed(color=couleur)
    embed.description = f"**<@{member.id}> (`{member.name}`)**\n🆔 `{member.id}`\n\n**{titre} :**\n```{raison}```"
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
    if mp is not None:
        embed.add_field(
            name="",
            value=(
                "✅ L'utilisateur a été prévenu en MP."
                if mp
                else "⚠️ L'utilisateur n'a pas pu être prévenu (ou mode silent)."
            ),
            inline=False,
        )
    embed.set_footer(text=f"🆔 {ref} • Mod : @{mod_name}")
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Erreur log : {e}")

async def purger_messages(channel, member_id, limit=10):
    try:
        msgs = [
            msg
            async for msg in channel.history(limit=50)
            if msg.author.id == member_id
        ][:limit]
        if msgs:
            if len(msgs) > 1:
                await channel.delete_messages(msgs)
            else:
                await msgs[0].delete()
    except Exception as e:
        print(f"Erreur purge messages : {e}")


# ==========================================
# EVENTS
# ==========================================

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user} (ID: {bot.user.id})")
    bot.add_view(TicketView())
    bot.add_view(TicketActionsView())
    print("Vues de tickets chargées !")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synchronisation de {len(synced)} commande(s) slash réussie.")
    except Exception as e:
        print(f"Erreur lors de la synchronisation des commandes : {e}")

@bot.event
async def on_member_join(member):
    global SALON_BIENVENUE_ID
    role = member.guild.get_role(ROLE_AUTO_ID)
    if role:
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"Erreur ajout rôle auto : {e}")

    channel = member.guild.get_channel(SALON_BIENVENUE_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="Ho ! Un nouveau membre !",
        description=f"🎉 Bienvenue {member.mention} 🎉 !",
        color=discord.Color.from_rgb(114, 137, 218),
    )
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
        
    try:
        await channel.send(content=f"{member.mention}", embed=embed)
    except Exception as e:
        print(f"Erreur bienvenue : {e}")

@bot.event
async def on_member_remove(member):
    global SALON_DEPART_ID
    channel = member.guild.get_channel(SALON_DEPART_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="Un membre vient de partir... 😢",
        description=f"À bientôt **{member.name}** ! 👋",
        color=discord.Color.from_rgb(217, 83, 79),
    )
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await channel.send(content=f"@{member.name}", embed=embed)
    except Exception as e:
        print(f"Erreur départ : {e}")

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    deleted_messages_cache[message.channel.id].append({
        "author_id": message.author.id,
        "author": str(message.author),
        "author_avatar": (
            message.author.display_avatar.url
            if message.author.display_avatar
            else None
        ),
        "content": message.content or "[Contenu vide / Image / Embed]",
        "time": datetime.now().strftime("%d/%m/%Y à %H:%M:%S"),
    })

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    if any(role.id in ROLES_AUTORISES for role in message.author.roles):
        await bot.process_commands(message)
        return

    maintenant = datetime.now()
    user_msgs = spam_cooldowns[message.author.id]
    user_msgs.append(maintenant)
    while user_msgs and (maintenant - user_msgs[0]) > timedelta(seconds=5):
        user_msgs.popleft()

    if len(user_msgs) >= 5:
        user_msgs.clear()
        role_mute = message.guild.get_role(ROLE_MUTE_ID)
        if role_mute and role_mute not in message.author.roles:
            try:
                await message.author.add_roles(role_mute, reason="Anti-spam automatique")
                enregistrer_action(
                    message.author.id,
                    "🔇 Auto-Mute (Spam)",
                    "Système",
                    "Trop de messages",
                )
                await purger_messages(message.channel, message.author.id, limit=10)

                mp_ok = True
                try:
                    await message.author.send(
                        f"🔇 Tu as été muté automatiquement pour **spam** sur **{message.guild.name}** pendant **5 minutes**."
                    )
                except:
                    mp_ok = False

                await envoyer_log_salon(
                    message.guild,
                    message.author,
                    "🔇 Auto-Mute & Purge",
                    "Spam détecté (10 messages purgés)",
                    "Système",
                    mp=mp_ok,
                    ref="s_6CAG8",
                    couleur=discord.Color.dark_grey(),
                )

                async def unmute_auto():
                    await asyncio.sleep(300)
                    if role_mute in message.author.roles:
                        try:
                            await message.author.remove_roles(
                                role_mute, reason="Fin auto-mute"
                            )
                            enregistrer_action(
                                message.author.id, "🔊 Auto-Unmute", "Système", "Fin de sanction"
                            )
                        except:
                            pass

                bot.loop.create_task(unmute_auto())
            except Exception as e:
                print(f"Erreur anti-spam : {e}")

    await bot.process_commands(message)


# ==========================================
# SYSTEME DE TICKETS
# ==========================================

class TicketActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Prendre", style=discord.ButtonStyle.primary, emoji="🙋‍♂️", custom_id="take_ticket_btn")
    async def take_ticket_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not est_admin_interaction(interaction):
            await interaction.response.send_message("❌ Seuls les administrateurs peuvent prendre ce ticket.", ephemeral=True)
            return

        button.disabled = True
        button.label = f"Pris par {interaction.user.name}"
        button.style = discord.ButtonStyle.secondary

        embed = discord.Embed(
            description=f"🔒 Ce ticket a été pris en charge par **{interaction.user.mention}**.",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not est_admin_interaction(interaction):
            await interaction.response.send_message("❌ Seuls les administrateurs peuvent fermer ce ticket.", ephemeral=True)
            return

        await interaction.response.send_message("🔒 Fermeture du ticket dans 5 secondes...", ephemeral=False)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Fermé par {interaction.user.name}")
        except Exception as e:
            print(f"Erreur suppression ticket : {e}")

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create ticket", style=discord.ButtonStyle.primary, emoji="📩", custom_id="create_ticket_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user

        existing_channel = None
        for channel in guild.text_channels:
            if channel.name.startswith(f"ticket-{member.name.lower()}"):
                permissions = channel.permissions_for(member)
                if permissions.read_messages:
                    existing_channel = channel
                    break

        if existing_channel:
            await interaction.response.send_message(f"❌ Tu as déjà un ticket ouvert : {existing_channel.mention}", ephemeral=True)
            return

        categorie = guild.get_channel(CATEGORIE_TICKET_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        for role_id in ROLES_AUTORISES:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            ticket_channel = await guild.create_text_channel(
                name=f"ticket-{member.name.lower()}",
                category=categorie if isinstance(categorie, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"Ticket ouvert par {member.name}"
            )

            embed = discord.Embed(
                title="Support Ticket",
                description=f"Bienvenue {member.mention} !\nExplique ton problème ici, un membre de l'équipe va te répondre rapidement.",
                color=discord.Color.green()
            )

            await ticket_channel.send(content=f"{member.mention}", embed=embed, view=TicketActionsView())
            await interaction.response.send_message(f"✅ Ton ticket a été créé avec succès : {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur lors de la création du ticket : {e}", ephemeral=True)


# ==========================================
# LOGIQUE COMMUNE SPAM
# ==========================================

async def logique_spam(destination_send, guild, author_name, member):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }

    for role_id in ROLES_AUTORISES:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    try:
        salon_spam = await guild.create_text_channel(
            name=f"spam-{member.name.lower()}",
            overwrites=overwrites,
            reason=f"Salon de spam créé par {author_name} pour {member.name}"
        )

        await destination_send(f"✅ Salon privé créé avec succès : {salon_spam.mention}")
        await salon_spam.send(f"⚠️ Salon de spam privé ouvert pour {member.mention} par {author_name}.")

        async def run_spam():
            try:
                i = 1
                while True:
                    await salon_spam.send(f"{member.mention} Spam de notification #{i}")
                    i += 1
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Erreur boucle spam : {e}")

        task = bot.loop.create_task(run_spam())
        active_spam_tasks[member.id] = task

    except Exception as e:
        await destination_send(f"❌ Erreur lors de la création du salon de spam : {e}")

async def logique_spamstop(destination_send, member):
    if member.id in active_spam_tasks:
        task = active_spam_tasks[member.id]
        if not task.done():
            task.cancel()
        del active_spam_tasks[member.id]
        await destination_send(f"✅ Le spam pour **{member.name}** a été arrêté avec succès.")
    else:
        await destination_send(f"❌ Aucune tâche de spam active trouvée pour **{member.name}**.")

async def logique_spamdelete(destination_send, guild, author_name, member):
    if member.id in active_spam_tasks:
        task = active_spam_tasks[member.id]
        if not task.done():
            task.cancel()
        del active_spam_tasks[member.id]

    salon_supprime = False
    for channel in guild.text_channels:
        if channel.name == f"spam-{member.name.lower()}":
            try:
                await channel.delete(reason=f"Supprimé par spamdelete (Admin: {author_name})")
                salon_supprime = True
            except Exception as e:
                print(f"Erreur suppression salon spam : {e}")

    if salon_supprime:
        await destination_send(f"✅ Spam stoppé et salon de **{member.name}** supprimé avec succès.")
    else:
        await destination_send(f"⚠️ Spam stoppé, mais aucun salon spécifique trouvé pour **{member.name}**.")

async def logique_spamdeleteall(guild, author_name):
    for member_id, task in list(active_spam_tasks.items()):
        if not task.done():
            task.cancel()
    active_spam_tasks.clear()

    salons_spam = [c for c in guild.text_channels if c.name.startswith("spam-")]
    return salons_spam


# ==========================================
# FONCTION PANNEAU D'AIDE COMMUN
# ==========================================
async def envoyer_panneau_aide(send_method):
    embed = discord.Embed(
        title="📜 Panneau d'Aide du Bot",
        description="Voici la liste de toutes les commandes disponibles (compatibles avec `!` et `/`) :",
        color=discord.Color.from_rgb(114, 137, 218)
    )
    embed.add_field(
        name="🛠️ Modération Classique (Admin)",
        value=(
            "`!clear <nombre>` / `/clear` - Supprime des messages.\n"
            "`!kick <membre>` / `/kick` - Expulse un membre.\n"
            "`!ban <membre>` / `/ban` - Bannit un membre."
        ),
        inline=False
    )
    embed.add_field(
        name="🎫 Modération & Tickets (Admin)",
        value=(
            "`!ping` / `/ping` - Affiche la latence du bot.\n"
            "`!take` / `/take` - Prend en charge un ticket.\n"
            "`!close` / `/close` - Ferme le ticket actuel.\n"
            "`!closeall` / `/closeall` - Ferme tous les tickets ouverts.\n"
            "`!ticketaddpanel` / `/ticketaddpanel` - Envoie le panneau de tickets."
        ),
        inline=False
    )
    embed.add_field(
        name="🚨 Gestion du Spam (Admin)",
        value=(
            "`!spam <membre>` / `/spam` - Crée un salon de spam privé.\n"
            "`!spamstop <membre>` / `/spamstop` - Arrête le spam en cours.\n"
            "`!spamdelete <membre>` / `/spamdelete` - Arrête et supprime le salon.\n"
            "`!spamdeleteall` / `/spamdeleteall` - Stoppe et supprime tous les spams."
        ),
        inline=False
    )
    embed.add_field(
        name="⚙️ Configuration & Rôles (Admin)",
        value=(
            "`!setwelcome <salon>` / `/setwelcome` - Définit le salon de bienvenue.\n"
            "`!setleave <salon>` / `/setleave` - Définit le salon de départ.\n"
            "`!roleadd <membres...> <id_role>` - Ajoute un rôle en masse.\n"
            "`!roleunadd <membres...> <id_role>` - Retire un rôle en masse."
        ),
        inline=False
    )
    embed.add_field(
        name="ℹ️ Aide",
        value="`!help`, `!?`, `/help` - Affiche ce panneau d'aide.",
        inline=False
    )
    embed.set_footer(text="Bot de gestion de serveur sécurisé")
    
    if hasattr(send_method, "response"):
        if send_method.response.is_done():
            await send_method.followup.send(embed=embed, ephemeral=True)
        else:
            await send_method.response.send_message(embed=embed, ephemeral=True)
    else:
        await send_method(embed=embed)


# ==========================================
# COMMANDES TEXTUELLES (!) ET SLASH (/)
# ==========================================

# --- AIDE (HELP & ??) ---
@bot.command(name="help")
async def help_text(ctx):
    if not est_admin_ctx(ctx): return
    await envoyer_panneau_aide(ctx.send)

@bot.command(name="?")
async def help_question_text(ctx):
    if not est_admin_ctx(ctx): return
    await envoyer_panneau_aide(ctx.send)

@bot.tree.command(name="help", description="Affiche la liste de toutes les commandes")
async def help_slash(interaction: discord.Interaction):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    await envoyer_panneau_aide(interaction)


# --- MODÉRATION CLASSIQUE : CLEAR ---
@bot.command(name="clear", aliases=["purge"])
async def clear_text(ctx, amount: int):
    if not est_admin_ctx(ctx): return
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"✅ {amount} message(s) supprimé(s).", delete_after=5)

@bot.tree.command(name="clear", description="Supprime un certain nombre de messages")
@app_commands.describe(amount="Le nombre de messages à supprimer")
async def clear_slash(interaction: discord.Interaction, amount: int):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ {len(deleted)} message(s) supprimé(s).", ephemeral=True)


# --- MODÉRATION CLASSIQUE : KICK ---
@bot.command(name="kick")
async def kick_text(ctx, member: discord.Member, *, reason: str = "Aucune raison fournie"):
    if not est_admin_ctx(ctx): return
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 **{member.name}** a été expulsé(e). Raison : {reason}")
    except Exception as e:
        await ctx.send(f"❌ Impossible d'expulser ce membre : {e}")

@bot.tree.command(name="kick", description="Expulse un membre du serveur")
@app_commands.describe(member="Le membre à expulser", reason="La raison de l'expulsion")
async def kick_slash(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 **{member.name}** a été expulsé(e). Raison : {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Impossible d'expulser ce membre : {e}", ephemeral=True)


# --- MODÉRATION CLASSIQUE : BAN ---
@bot.command(name="ban")
async def ban_text(ctx, member: discord.Member, *, reason: str = "Aucune raison fournie"):
    if not est_admin_ctx(ctx): return
    try:
        await member.ban(reason=reason)
        await ctx.send(f"🔨 **{member.name}** a été banni(e). Raison : {reason}")
    except Exception as e:
        await ctx.send(f"❌ Impossible de bannir ce membre : {e}")

@bot.tree.command(name="ban", description="Bannit un membre du serveur")
@app_commands.describe(member="Le membre à bannir", reason="La raison du bannissement")
async def ban_slash(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison fournie"):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 **{member.name}** a été banni(e). Raison : {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Impossible de bannir ce membre : {e}", ephemeral=True)


# --- PING ---
@bot.command(name="ping")
async def ping_text(ctx):
    if not est_admin_ctx(ctx): return
    await ctx.send(f"🏓 Pong ! **{round(bot.latency * 1000)} ms**")

@bot.tree.command(name="ping", description="Affiche la latence du bot")
async def ping_slash(interaction: discord.Interaction):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    await interaction.response.send_message(f"🏓 Pong ! **{round(bot.latency * 1000)} ms**")


# --- TAKE (TICKET) ---
@bot.command(name="take")
async def take_text(ctx):
    if not est_admin_ctx(ctx): return
    if not ctx.channel.name.startswith("ticket-"):
        await ctx.send("❌ Cette commande ne peut être utilisée que dans un salon de ticket.", delete_after=5)
        return

    embed = discord.Embed(
        description=f"🔒 Ce ticket a été pris en charge par **{ctx.author.mention}**.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.tree.command(name="take", description="Prend en charge le ticket actuel")
async def take_slash(interaction: discord.Interaction):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un salon de ticket.", ephemeral=True)
        return

    embed = discord.Embed(
        description=f"🔒 Ce ticket a été pris en charge par **{interaction.user.mention}**.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)


# --- CLOSE ---
@bot.command(name="close")
async def close_text(ctx):
    if not est_admin_ctx(ctx): return
    if not ctx.channel.name.startswith("ticket-"):
        await ctx.send("❌ Cette commande ne peut être utilisée que dans un salon de ticket.", delete_after=5)
        return
    
    await ctx.send("🔒 Fermeture du ticket dans 5 secondes...")
    await asyncio.sleep(5)
    try:
        await ctx.channel.delete(reason=f"Fermé par commande admin de {ctx.author.name}")
    except Exception as e:
        print(f"Erreur suppression ticket : {e}")

@bot.tree.command(name="close", description="Ferme le ticket actuel")
async def close_slash(interaction: discord.Interaction):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un salon de ticket.", ephemeral=True)
        return
    
    await interaction.response.send_message("🔒 Fermeture du ticket dans 5 secondes...")
    await asyncio.sleep(5)
    try:
        await interaction.channel.delete(reason=f"Fermé par commande admin de {interaction.user.name}")
    except Exception as e:
        print(f"Erreur suppression ticket : {e}")


# --- CLOSEALL ---
@bot.command(name="closeall")
async def closeall_text(ctx):
    if not est_admin_ctx(ctx): return
    guild = ctx.guild
    tickets = [c for c in guild.text_channels if c.name.startswith("ticket-")]
    if not tickets:
        await ctx.send("📂 Aucun ticket ouvert trouvé.", delete_after=5)
        return

    msg = await ctx.send(f"⚠️ Suppression de **{len(tickets)}** ticket(s) en cours...")
    for ticket in tickets:
        try:
            await ticket.delete(reason=f"Fermeture globale par {ctx.author.name}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Erreur suppression {ticket.name}: {e}")
    try:
        await msg.edit(content="✅ Tous les tickets ouverts ont été fermés.")
    except:
        pass

@bot.tree.command(name="closeall", description="Ferme tous les tickets ouverts")
async def closeall_slash(interaction: discord.Interaction):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    guild = interaction.guild
    tickets = [c for c in guild.text_channels if c.name.startswith("ticket-")]
    if not tickets:
        await interaction.response.send_message("📂 Aucun ticket ouvert trouvé.", ephemeral=True)
        return

    await interaction.response.send_message(f"⚠️ Suppression de **{len(tickets)}** ticket(s) en cours...")
    for ticket in tickets:
        try:
            await ticket.delete(reason=f"Fermeture globale par {interaction.user.name}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Erreur suppression {ticket.name}: {e}")
    try:
        await interaction.edit_original_response(content="✅ Tous les tickets ouverts ont été fermés.")
    except:
        pass


# --- SPAM ---
@bot.command(name="spam")
async def spam_text(ctx, member: discord.Member):
    if not est_admin_ctx(ctx): return
    await logique_spam(ctx.send, ctx.guild, ctx.author.name, member)

@bot.tree.command(name="spam", description="Crée un salon de spam privé pour un membre")
@app_commands.describe(member="Le membre à cibler")
async def spam_slash(interaction: discord.Interaction, member: discord.Member):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await logique_spam(interaction.followup.send, interaction.guild, interaction.user.name, member)


# --- SPAMSTOP ---
@bot.command(name="spamstop")
async def spamstop_text(ctx, member: discord.Member):
    if not est_admin_ctx(ctx): return
    await logique_spamstop(ctx.send, member)

@bot.tree.command(name="spamstop", description="Arrête le spam en cours pour un membre")
@app_commands.describe(member="Le membre concerné")
async def spamstop_slash(interaction: discord.Interaction, member: discord.Member):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    await logique_spamstop(interaction.response.send_message, member)


# --- SPAMDELETE ---
@bot.command(name="spamdelete")
async def spamdelete_text(ctx, member: discord.Member):
    if not est_admin_ctx(ctx): return
    await logique_spamdelete(ctx.send, ctx.guild, ctx.author.name, member)

@bot.tree.command(name="spamdelete", description="Arrête le spam et supprime le salon associé au membre")
@app_commands.describe(member="Le membre concerné")
async def spamdelete_slash(interaction: discord.Interaction, member: discord.Member):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await logique_spamdelete(interaction.followup.send, interaction.guild, interaction.user.name, member)


# --- SPAMDELETEALL ---
@bot.command(name="spamdeleteall")
async def spamdeleteall_text(ctx):
    if not est_admin_ctx(ctx): return
    salons_spam = await logique_spamdeleteall(ctx.guild, ctx.author.name)
    if not salons_spam:
        await ctx.send("📂 Aucun salon de spam actif trouvé à supprimer.", delete_after=5)
        return

    msg = await ctx.send(f"⚠️ Suppression de **{len(salons_spam)}** salon(s) de spam en cours...")
    for channel in salons_spam:
        try:
            await channel.delete(reason=f"Suppression globale spam par {ctx.author.name}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Erreur suppression {channel.name}: {e}")
    try:
        await msg.edit(content=f"✅ Tous les spams ont été stoppés et **{len(salons_spam)}** salon(s) de spam ont été supprimés.")
    except:
        pass

@bot.tree.command(name="spamdeleteall", description="Arrête tous les spams et supprime tous les salons spam")
async def spamdeleteall_slash(interaction: discord.Interaction):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    salons_spam = await logique_spamdeleteall(interaction.guild, interaction.user.name)
    if not salons_spam:
        await interaction.response.send_message("📂 Aucun salon de spam actif trouvé à supprimer.", ephemeral=True)
        return

    await interaction.response.send_message(f"⚠️ Suppression de **{len(salons_spam)}** salon(s) de spam en cours...")
    for channel in salons_spam:
        try:
            await channel.delete(reason=f"Suppression globale spam par {interaction.user.name}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Erreur suppression {channel.name}: {e}")
    try:
        await interaction.edit_original_response(content=f"✅ Tous les spams ont été stoppés et **{len(salons_spam)}** salon(s) de spam ont été supprimés.")
    except:
        pass


# --- TICKETADDPANEL ---
@bot.command(name="ticketaddpanel")
async def ticketaddpanel_text(ctx, channel: discord.TextChannel = None):
    if not est_admin_ctx(ctx): return
    target_channel = channel or ctx.channel
    embed = discord.Embed(
        title="ticket",
        description="To create a ticket use the Create ticket button",
        color=discord.Color.from_rgb(46, 204, 113)
    )
    try:
        await target_channel.send(embed=embed, view=TicketView())
        if target_channel != ctx.channel:
            await ctx.send(f"✅ Panneau de tickets envoyé avec succès dans {target_channel.mention} !")
        else:
            await ctx.message.delete()
    except Exception as e:
        await ctx.send(f"❌ Erreur lors de l'envoi du panneau : {e}")

@bot.tree.command(name="ticketaddpanel", description="Envoie le panneau de création de tickets")
@app_commands.describe(channel="Le salon cible (optionnel)")
async def ticketaddpanel_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    target_channel = channel or interaction.channel
    embed = discord.Embed(
        title="ticket",
        description="To create a ticket use the Create ticket button",
        color=discord.Color.from_rgb(46, 204, 113)
    )
    try:
        await target_channel.send(embed=embed, view=TicketView())
        await interaction.response.send_message(f"✅ Panneau de tickets envoyé dans {target_channel.mention} !", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)


# --- CONFIGURATION SALONS ---
@bot.command(name="setwelcome")
async def setwelcome_text(ctx, channel: discord.TextChannel):
    if not est_admin_ctx(ctx): return
    global SALON_BIENVENUE_ID
    SALON_BIENVENUE_ID = channel.id
    await ctx.send(f"✅ Salon de bienvenue défini sur {channel.mention} !")

@bot.tree.command(name="setwelcome", description="Définit le salon de bienvenue")
@app_commands.describe(channel="Le salon textuel")
async def setwelcome_slash(interaction: discord.Interaction, channel: discord.TextChannel):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    global SALON_BIENVENUE_ID
    SALON_BIENVENUE_ID = channel.id
    await interaction.response.send_message(f"✅ Salon de bienvenue défini sur {channel.mention} !")

@bot.command(name="setleave")
async def setleave_text(ctx, channel: discord.TextChannel):
    if not est_admin_ctx(ctx): return
    global SALON_DEPART_ID
    SALON_DEPART_ID = channel.id
    await ctx.send(f"✅ Salon de départ défini sur {channel.mention} !")

@bot.tree.command(name="setleave", description="Définit le salon de départ")
@app_commands.describe(channel="Le salon textuel")
async def setleave_slash(interaction: discord.Interaction, channel: discord.TextChannel):
    if not est_admin_interaction(interaction):
        await interaction.response.send_message("❌ Tu n'as pas la permission.", ephemeral=True)
        return
    global SALON_DEPART_ID
    SALON_DEPART_ID = channel.id
    await interaction.response.send_message(f"✅ Salon de départ défini sur {channel.mention} !")


# --- ROLEADD / ROLEUNADD ---
@bot.command(name="roleadd")
async def roleadd_text(ctx, members: commands.Greedy[discord.Member], role_id: int):
    if not est_admin_ctx(ctx): return
    if not members:
        await ctx.send("❌ Tu dois spécifier au moins un membre valide.", delete_after=5)
        return
    role = ctx.guild.get_role(role_id)
    if not role:
        await ctx.send(f"❌ Aucun rôle trouvé avec l'ID `{role_id}`.", delete_after=5)
        return
    succes = 0
    for member in members:
        try:
            if role not in member.roles:
                await member.add_roles(role, reason=f"Ajout en masse par {ctx.author.name}")
                succes += 1
        except Exception as e:
            print(f"Erreur ajout rôle pour {member.name}: {e}")
    await ctx.send(f"✅ Rôle **{role.name}** ajouté avec succès à **{succes}** membre(s).", delete_after=5)

@bot.command(name="roleunadd")
async def roleunadd_text(ctx, members: commands.Greedy[discord.Member], role_id: int):
    if not est_admin_ctx(ctx): return
    if not members:
        await ctx.send("❌ Tu dois spécifier au moins un membre valide.", delete_after=5)
        return
    role = ctx.guild.get_role(role_id)
    if not role:
        await ctx.send(f"❌ Aucun rôle trouvé avec l'ID `{role_id}`.", delete_after=5)
        return
    succes = 0
    for member in members:
        try:
            if role in member.roles:
                await member.remove_roles(role, reason=f"Retrait en masse par {ctx.author.name}")
                succes += 1
        except Exception as e:
            print(f"Erreur retrait rôle pour {member.name}: {e}")
    await ctx.send(f"✅ Rôle **{role.name}** retiré avec succès à **{succes}** membre(s).", delete_after=5)


# Lancement du bot avec le token caché
bot.run(os.getenv("DISCORD_TOKEN"))
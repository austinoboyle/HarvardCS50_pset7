from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from passlib.apps import custom_app_context as pwd_context
from tempfile import gettempdir
import sqlalchemy

from helpers import *

# configure application
app = Flask(__name__)

# ensure responses aren't cached
if app.config["DEBUG"]:
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response

# custom filter
app.jinja_env.filters["usd"] = usd

# configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = gettempdir()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

@app.route("/settings", methods = ["GET"])
@login_required
def settings():
    return render_template("settings.html")
    
@app.route("/password", methods = ["POST", "GET"])
@login_required
def password():
    if request.method == "POST":
        # query database for username
        userInfo = db.execute("SELECT * FROM users WHERE id = :userId", userId = session["user_id"])
        
        oldPassword = request.form.get("old_password")
        newPassword = request.form.get("new_password")
        confirmPassword = request.form.get("confirm_password")
        
        #Check if fields are left blank
        if (oldPassword == "") or (newPassword == ""):
            flash("ERROR: Must fill in all fields of the form")
            return redirect(url_for("password"))
            
        #Make sure old password matches new password    
        elif not pwd_context.verify(oldPassword, userInfo[0]["hash"]):
            flash("Invalid Old Password")
            return redirect(url_for("password"))
        
        #Make sure password confirmation matches the desired new password    
        elif newPassword != confirmPassword:
            flash("ERROR: Updated password did not match confirmation")
            return redirect(url_for("password"))
        
        else:
            db.execute("UPDATE users SET hash = :newHash WHERE id = :userId",\
                newHash = pwd_context.encrypt(newPassword),\
                userId = session["user_id"])
            flash("Password updated.")
            return redirect(url_for("settings"))
    else:

        return render_template("password.html")
    
@app.route("/deposit", methods = ["POST", "GET"])
@login_required
def deposit():
    if request.method == "POST":
        amount = request.form.get("amount")
        
        if not isFloat(amount):
            flash("ERROR: Invalid Amount")
            return redirect(url_for("deposit"))
            
        amount = toFloat(amount)
        cash = db.execute("SELECT * FROM users WHERE id = :userId",\
            userId = session["user_id"])[0]['cash']
            
        db.execute("UPDATE users SET cash = :newTotal WHERE id = :userId",\
            userId = session["user_id"],\
            newTotal = cash+amount)
            
        flash("Added ${:.2f} to account".format(amount))
        return redirect(url_for("settings"))
        
    else:
        return render_template("deposit.html")

@app.route("/")
@login_required
def index():
    userId = session["user_id"]
    portfolio = db.execute("SELECT * FROM portfolios WHERE username_id = :userId",\
        userId = userId)[0]
    
    companies = list(portfolio.keys())
    companies.remove("username_id")
    cash = db.execute("SELECT * FROM users WHERE id=:userId", userId = userId)[0]['cash']
    nonZeroCompanies = []

    outerDict = {}
    totalAssets = cash
    for company in companies:
        stockinfo = lookup(company)
        if portfolio[company] > 0:
            nonZeroCompanies.append(company)
            outerDict[company] = {}
            outerDict[company]['symbol'] = company
            outerDict[company]['name'] = stockinfo['name']
            outerDict[company]['shares'] = portfolio[company]
            outerDict[company]['price'] = stockinfo['price']
            outerDict[company]['total'] = stockinfo['price'] * portfolio[company]
            totalAssets += outerDict[company]['total']
    
        
    return render_template("portfolio.html", cash = usd(cash), companies = nonZeroCompanies,\
                            dict = outerDict, totalAssets = usd(totalAssets))
    
@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        quantity = request.form.get("quantity")
        quote = lookup(symbol)
        if not quote:
            return apology("Stock doesn't exist")
            
        if not quantity.isdigit() or quantity == '0':
            return apology("Invalid quantity")
        quantity = int(quantity)    
        
        cash = db.execute("SELECT cash FROM users WHERE id = :userId",\
            userId = session["user_id"])[0]['cash']
        
        if cash < quote['price'] * quantity:
            return apology("You are too poor")
        
        newTotal = cash - quantity * quote['price']
           
        db.execute("UPDATE users SET cash = :total WHERE id = :userId", total = newTotal, userId = session["user_id"])
        
        #Try and add the shares to the current number in the users portfolio
        try:
            currentTotal = db.execute("SELECT * FROM portfolios WHERE username_id = :userId",\
                userId = session["user_id"])[0][symbol]
            newTotal = currentTotal + quantity
            
            db.execute("UPDATE portfolios SET :symbol = :newTotal WHERE username_id = :userId",\
                symbol = symbol,\
                newTotal = newTotal,\
                userId = session["user_id"])
        
        #Company is not in the database yet, so add it
        except KeyError:
            try:
                addRow = db.execute('ALTER TABLE "portfolios" ADD :symbol INTEGER NOT NULL DEFAULT 0', symbol = symbol)
                newTotal = db.execute("SELECT * FROM portfolios WHERE username_id = :userId",\
                    userId = session["user_id"])[0][symbol] + quantity
                    
                db.execute("UPDATE portfolios SET :symbol = :newTotal WHERE username_id = :userId",\
                    symbol = symbol,\
                    newTotal = newTotal,\
                    userId = session["user_id"])
            except:
                flash("Error")
                return redirect(url_for("buy.html"))
        
        transactionId = db.execute("INSERT INTO transactions (username_id, symbol, company, price, quantity) \
            VALUES(:userId, :symbol, :company, :price, :quantity)",\
            userId = session["user_id"],\
            symbol = symbol,\
            company = quote['name'],\
            price = quote['price'],\
            quantity = quantity)
        
        if not transactionId:
            return apology("Error adding the transaction")
        
        flash('Successfully bought {} shares of {}!'.format(quantity, symbol))
        return redirect(url_for("index"))
    else:
        return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    transactions = db.execute("SELECT * from transactions WHERE username_id = :userId",\
        userId = session["user_id"])
    return render_template("history.html", transactions = transactions)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in."""

    # forget any user_id
    session.clear()

    # if user reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username")

        # ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password")

        # query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))

        # ensure username exists and password is correct
        if len(rows) != 1 or not pwd_context.verify(request.form.get("password"), rows[0]["hash"]):
            return apology("invalid username and/or password")

        # remember which user has logged in
        session["user_id"] = rows[0]["id"]
        session["username"] = request.form.get("username")

        # redirect user to home page
        return redirect(url_for("index"))

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out."""

    # forget any user_id
    session.clear()

    # redirect user to login form
    return redirect(url_for("login"))

@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        if not symbol:
            return url_for("quote")
        
        quote = lookup(symbol.upper())
        
        if not quote:
            return apology("Stock symbol doesn't exist")
        
        company = quote['name']
        price = quote['price']
        
        return render_template("quotedisplay.html", company=company, symbol=symbol.upper(), price=usd(price))
    else:
        return render_template("quotesearch.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    session.clear()
    
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        if not username:
            return apology("Must provide username")
        elif not password:
            return apology("Must enter a password")
        elif password != confirm_password:
            return apology("Password confirmation doesn't match password")
            
        userId = db.execute("INSERT INTO users (username, hash, cash) VALUES(:username, :hash, :cash)",\
        username=username, hash=pwd_context.encrypt(password), cash=10000)
        
        if not userId:
            return apology("Username already has an account")
        
        userId = db.execute("SELECT * FROM users WHERE username = :username",\
            username = username)[0]['id']
        
        userPortfolio = db.execute("INSERT INTO portfolios (username_id) VALUES(:userId)",userId = userId)
        print (userPortfolio)
        
        if not userPortfolio:
            return apology("Error adding new portfolio")
             
        session["user_id"] = userId
        session["username"] = request.form.get("username")
        flash('Successfully registered!')
        return redirect(url_for("index"))
    else:
        return render_template("register.html")
    

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        quantity = request.form.get("quantity")
        quote = lookup(symbol)
        if not quote:
            return apology("Stock doesn't exist")
            
        if not quantity.isdigit() or quantity == '0':
            return apology("Invalid quantity")
        quantity = int(quantity)    
        
        cash = db.execute("SELECT cash FROM users WHERE id = :userId",\
            userId = session["user_id"])[0]['cash']
        
        try:
            numberOwned = db.execute("SELECT * FROM portfolios WHERE username_id = :userId",\
            userId = session["user_id"])[0][symbol]
        except KeyError:
            return apology("You don't own any shares of that stock!")
        
        if numberOwned < quantity:
            return apology("You don't own that many shares of {}".format(symbol))
        
        newTotal = cash + quantity * quote['price']
           
        db.execute("UPDATE users SET cash = :total WHERE id = :userId", total = newTotal, userId = session["user_id"])
        
        transactionId = db.execute("INSERT INTO transactions (username_id, symbol, company, price, quantity) \
            VALUES(:userId, :symbol, :company, :price, :quantity)",\
            userId = session["user_id"],\
            symbol = symbol,\
            company = quote['name'],\
            price = quote['price'],\
            quantity = -quantity)
        
        if not transactionId:
            return apology("Error adding the transaction")
        
        transactions = db.execute("SELECT * FROM transactions WHERE username_id = :userId",\
        userId = session["user_id"])
        
        currentTotal = db.execute("SELECT * FROM portfolios WHERE username_id = :userId",\
            userId = session["user_id"])[0][symbol]
        
        newTotal = currentTotal - quantity
        
        try:
            db.execute("UPDATE portfolios SET :symbol = :newTotal WHERE username_id = :userId",\
                symbol = symbol,\
                newTotal = newTotal,\
                userId = session["user_id"])
        except:
            return apology("Error subtracting shares from portfolio")
        
        flash('Successfully sold {} shares of {}!'.format(quantity, symbol))
        
        return redirect(url_for("index"))
    else:
        return render_template("sell.html")

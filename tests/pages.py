"""HTML fixtures replicating the *actually observed* public layouts of t.me
and fragment.com (recorded from the live sites on 2026-07-30).

Every marker the adapters rely on (page titles, counters, preview links,
status badges, labelled price tables) appears here exactly as observed.
"""

# ---------------------------------------------------------------------------
# t.me pages
# ---------------------------------------------------------------------------

TELE_CHANNEL_HTML = """<!DOCTYPE html>
<html><head>
<title>Telegram: View @durov</title>
<meta property="og:title" content="Telegram: View @durov">
<meta property="og:description" content="Pavel Durov. 11 419 432 subscribers. Founder of Telegram.">
</head><body class="tgme_page">
<a class="tgme_page_photo" href="tg://resolve?domain=durov"><img src="https://cdn4.telesco.pe/file/abc.jpg"></a>
<div class="tgme_page_title"><span dir="auto">Pavel Durov</span> <i class="verified-icon"></i></div>
<div class="tgme_page_additional">11 419 432 subscribers</div>
<div class="tgme_page_description">Founder of Telegram.</div>
<a class="tgme_action_button_new" href="tg://resolve?domain=durov">View in Telegram</a>
<a class="tgme_action_button_new shine" href="https://t.me/s/durov">Preview channel</a>
<div class="tgme_page_hint_text">If you have <strong>Telegram</strong>, you can view and join
<strong>Pavel Durov</strong> right away.</div>
</body></html>"""

TELE_GROUP_HTML = """<!DOCTYPE html>
<html><head>
<title>Telegram: View @durovschat</title>
<meta property="og:title" content="Telegram: View @durovschat">
</head><body class="tgme_page">
<a class="tgme_page_photo" href="tg://resolve?domain=durovschat"><img src="https://cdn4.telesco.pe/file/def.jpg"></a>
<div class="tgme_page_title"><span dir="auto">Du Rove's Chat</span></div>
<div class="tgme_page_additional">9 897 members, 1 195 online</div>
<div class="tgme_page_description">Rules: no spam, no porn, no gore.</div>
<a class="tgme_action_button_new" href="tg://resolve?domain=durovschat">View in Telegram</a>
<div class="tgme_page_hint_text">If you have <strong>Telegram</strong>, you can view and join
<strong>Du Rove's Chat</strong> right away.</div>
</body></html>"""

TELE_BOT_HTML = """<!DOCTYPE html>
<html><head>
<title>Telegram: Launch @BotFather</title>
<meta property="og:title" content="Telegram: Launch @BotFather">
</head><body class="tgme_page">
<a class="tgme_page_photo" href="tg://resolve?domain=BotFather"><img src="https://cdn1.telesco.pe/file/ghi.jpg"></a>
<div class="tgme_page_title"><span dir="auto">BotFather</span> <i class="verified-icon"></i></div>
<div class="tgme_page_extra">@BotFather</div>
<div class="tgme_page_additional">8 241 294 monthly users</div>
<div class="tgme_page_description">BotFather is the one bot to rule them all.</div>
<a class="tgme_action_button_new" href="tg://resolve?domain=BotFather">Start Bot</a>
<div class="tgme_page_hint_text">If you have <strong>Telegram</strong>, you can launch
<strong>BotFather</strong> right away.</div>
</body></html>"""

TELE_BARE_HTML = """<!DOCTYPE html>
<html><head>
<title>Telegram: Contact @wqxjvkzq</title>
<meta property="og:title" content="Telegram: Contact @wqxjvkzq">
</head><body class="tgme_page">
<div class="tgme_page_hint_text">If you have <strong>Telegram</strong>, you can contact
<a href="tg://resolve?domain=wqxjvkzq">@wqxjvkzq</a> right away.</div>
<a class="tgme_action_button_new" href="tg://resolve?domain=wqxjvkzq">Send Message</a>
</body></html>"""

TELE_BARE_SUPPORT_HTML = TELE_BARE_HTML.replace("wqxjvkzq", "support")

TELE_GARBAGE_HTML = "<html><head><title>t.me</title></head><body>Please enable JavaScript</body></html>"

TELEGRAM_ORG_HTML = """<!DOCTYPE html>
<html><head><title>Telegram Messenger</title></head><body><h1>a new era of messaging</h1></body></html>"""

# ---------------------------------------------------------------------------
# fragment.com pages
# ---------------------------------------------------------------------------

FRAG_TAKEN_HTML = """<!DOCTYPE html>
<html><head><title>durov – Fragment</title></head><body>
<div class="tm-section-header">
  <h1 class="tm-section-header-domain"><span>durov</span><span class="tm-section-header-tld">.t.me</span></h1>
  <div class="tm-section-header-status">Taken</div>
</div>
<p>Someone already claimed this username on Telegram. You can make an offer, which we will forward to the owner &ndash; who may be encouraged to sell.</p>
<table class="tm-table"><tr><td>Telegram Username</td><td>@durov</td></tr>
<tr><td>Web Address</td><td>t.me/durov</td></tr><tr><td>TON Web 3.0 Address</td><td>durov.t.me</td></tr></table>
<a class="tm-btn">Make an offer</a>
<h3>Latest Offers</h3>
<table class="tm-table"><tr><th>Offer</th><th>Date</th><th>Offered by</th></tr>
<tr><td>3</td><td>Mar 17, 2024 at 15:36</td><td>UQBsfrfa</td></tr></table>
</body></html>"""

FRAG_AUCTION_HTML = """<!DOCTYPE html>
<html><head><title>polymarket – Fragment</title></head><body>
<div class="tm-section-header">
  <h1 class="tm-section-header-domain"><span>polymarket</span><span class="tm-section-header-tld">.t.me</span></h1>
  <div class="tm-section-header-status">On auction</div>
</div>
<table class="tm-table">
<tr><th>Highest Bid</th><th>Bid Step</th><th>Minimum Bid</th></tr>
<tr><td>354,900<br>~ $504,939</td><td>17,745<br>5%</td><td>372,645<br>~ $530,186</td></tr>
</table>
<table class="tm-table"><tr><td>Telegram Username</td><td>@polymarket</td></tr>
<tr><td>Web Address</td><td>t.me/polymarket</td></tr><tr><td>TON Web 3.0 Address</td><td>polymarket.t.me</td></tr></table>
<div class="tm-timer-wrap">Ends in <span class="js-timer">1 day 18 hours 31 minutes</span></div>
<div>Auction will close soon</div>
<a class="tm-btn">Place bid</a><a class="tm-btn">Buy for 1,000,000</a>
<h3>Bid History</h3>
<table class="tm-table"><tr><th>Price</th><th>Date</th><th>From</th></tr>
<tr><td>354,900</td><td>Jul 29 at 04:42</td><td>zachary-t-me.ton</td></tr></table>
</body></html>"""

FRAG_FOR_SALE_HTML = """<!DOCTYPE html>
<html><head><title>scalp – Fragment</title></head><body>
<div class="tm-section-header">
  <h1 class="tm-section-header-domain"><span>scalp</span><span class="tm-section-header-tld">.t.me</span></h1>
  <div class="tm-section-header-status">For sale</div>
</div>
<table class="tm-table">
<tr><th>Sell Price <span class="tm-table-th-note">*</span></th></tr>
<tr><td>4,750<br>~ $6,755</td></tr>
</table>
<p>* The owner of this asset is ready to sell it for this price without an auction.</p>
<table class="tm-table"><tr><td>Telegram Username</td><td>@scalp</td></tr>
<tr><td>Web Address</td><td>t.me/scalp</td></tr><tr><td>TON Web 3.0 Address</td><td>scalp.t.me</td></tr></table>
<a class="tm-btn">Buy for 4,750</a>
<h3>Ownership History</h3>
<table class="tm-table"><tr><th>Sale price</th><th>Date</th><th>Buyer</th></tr>
<tr><td>515</td><td>Dec 10, 2025 at 23:47</td><td>UQB2eevu</td></tr></table>
</body></html>"""

FRAG_AVAILABLE_HTML = """<!DOCTYPE html>
<html><head><title>stormed – Fragment</title></head><body>
<div class="tm-section-header">
  <h1 class="tm-section-header-domain"><span>stormed</span><span class="tm-section-header-tld">.t.me</span></h1>
  <div class="tm-section-header-status">Available</div>
</div>
<table class="tm-table">
<tr><th>Minimum Bid</th></tr>
<tr><td>563<br>~ $800.61</td></tr>
</table>
<table class="tm-table"><tr><td>Telegram Username</td><td>@stormed</td></tr>
<tr><td>Web Address</td><td>t.me/stormed</td></tr><tr><td>TON Web 3.0 Address</td><td>stormed.t.me</td></tr></table>
<a class="tm-btn">Place bid and start auction</a>
</body></html>"""

FRAG_PAGE_WITHOUT_BADGE_HTML = """<!DOCTYPE html>
<html><head><title>oddname – Fragment</title></head><body>
<div class="tm-section-header">
  <h1 class="tm-section-header-domain"><span>oddname</span><span class="tm-section-header-tld">.t.me</span></h1>
</div>
<p>This layout no longer contains any known status badge or price labels.</p>
</body></html>"""

FRAG_SEARCH_EMPTY_HTML = """<!DOCTYPE html>
<html><head><title>Fragment</title></head><body>
<h1>Buy and Sell Usernames</h1>
<h2>Results Search Results</h2>
<div>Auctions not found.</div>
</body></html>"""

FRAG_GARBAGE_HTML = "<html><head><title>Just a moment...</title></head><body>Checking your browser before accessing fragment.com</body></html>"

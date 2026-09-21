## Goal
Build amazon.com clone. The goal is not to reproduce every Amazon feature. The clone should focus on the primary customer journey.

## Scope In

### 1. Landing / Product Discovery
- Amazon-inspired landing page.
- Display a catalog of products.
- Each product should show the information necessary to make it useful while
  browsing, such as:
  - image
  - title
  - price
  - rating
- Clicking a product opens its product detail page.

### 2. Product Search
- Search products by name or relevant product information.
- Search results should display matching products using the same product
  presentation used elsewhere in the application.

Search is included because finding products is a core part of the Amazon
shopping experience.

### 3. Product Categories
- Products belong to categories.
- Users can browse/filter products by category.

### 4. Product Detail Page
Each product has its own page containing the important purchasing information, based on the Amazon product-page reference:
- product images
- product title
- price
- rating
- product description / key information
- quantity selection
- Add to Cart

### 5. Cart
Users can:
- add products to the cart
- view products currently in the cart
- change quantity
- remove products
- see the subtotal
Cart state should persist appropriately across navigation/refreshes.

### 6. Authentication
Provide basic account functionality:
- sign up
- sign in
- sign out

## Scope Out

The following are intentionally excluded because they are not necessary to
demonstrate the core shopping experience:
- Amazon Prime / Prime membership functionality
- Alexa
- gift cards
- coupons and promotions
- seller functionality
- customer review creation
- recommendation engine
- order history and tracking
- wish lists
- customer service
- real inventory management
- complex shipping and fulfillment
- payment processing
- Amazon's full category/navigation hierarchy
- Checkout: A production checkout and payment system is out of scope. The cart may expose "Proceed to Checkout" action for UI completeness but the real payment, shipping and order fulfillment is out of scope. 

## Product Principle

When deciding whether to add functionality, prioritize features that directly support the primary shopping journey.
Features outside that journey should not be added unless its completes the core experience.
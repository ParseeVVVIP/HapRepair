@Entry
@Component
struct App {
  private products: Product[] = [];

  build() {
    Column() {
      ForEach(this.products, (product: Product) => {
        Text(product.name)
      });
    }
  }
}
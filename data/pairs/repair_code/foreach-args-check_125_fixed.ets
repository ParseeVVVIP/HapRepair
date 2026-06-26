@Entry
@Component
struct App {
  @State products: Product[] = [];

  build() {
    Column() {
      ForEach(this.products, (product: Product) => {
        // TODO: Add UI components for each product
      }, (product: Product) => product.productCode)
    }
  }
}
@Entry
@Component
struct App {
  @State books: Book[] = [];

  build() {
    Stack() {
      ForEach(this.books, (book: Book) => {
        BookItem({ book: book });
      }, (book: Book) => book.id);
    }
  }
}
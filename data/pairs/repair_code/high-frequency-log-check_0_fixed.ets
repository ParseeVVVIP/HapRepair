@Entry
@Component
struct Index {
  scroller: Scroller = new Scroller()

  build() {
      Column() {
        Scroll(this.scroller)
          .onScroll(() => {
            const TAG = 'onScroll';
          })
      }
  }
}
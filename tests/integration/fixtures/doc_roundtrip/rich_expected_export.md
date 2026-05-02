# Rich round-trip input

 Markdown that exercises features the converter degrades on: tables, images, inline formatting (**bold**, _italic_, [links](https://example.test/)), and nested lists.

## Inline formatting

 This paragraph has **bold**, _italic_, and a [link](https://example.test/) — all inline, expected to lose styling on round-trip.

## A table

|  Name |  Value |
| --- | --- |
|  Alpha |  1 |
|  Beta |  2 |

## An image

![Image: ](https://example.test/img.png)

## A nested list

-  top-level one

   -  nested A

   -  nested B

-  top-level two

   -  nested C

      -  deeply nested

## Code block

```typescript
const greeting: string = "hello";
```

 End of rich input.

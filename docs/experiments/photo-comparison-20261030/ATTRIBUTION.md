# 圖源、改動及個別素材授權

此文件只說明第三方圖片與其改作，不新增整個repo或原始碼的授權。repo原本沒有LICENSE；不得把照片的CC條款當成全部程式碼授權。

- 色字：nwales，[原始問題與圖片](https://stackoverflow.com/questions/28223727/how-to-achieve-adaptive-threshold-filter-with-color)，2015年貢獻，依[Stack Overflow時間政策](https://stackoverflow.com/help/licensing)適用[CC BY-SA3.0](https://creativecommons.org/licenses/by-sa/3.0/)。prepared/colour.png為等比RGB PNG；第一張診斷圖另加框、文字與排版，該含色字照片的合成PNG依CC BY-SA3.0提供。
- 水果：Daniel Rosehill，[Whiteboards資料集](https://huggingface.co/datasets/danielrosehill/Whiteboards)，revision 4b31e86e15743ffea20204a8f6992b0173ecbdf9、sample06，[CC BY4.0](https://creativecommons.org/licenses/by/4.0/)。prepared/fruits.png等比縮小，兩張診斷圖增加實際模型框、標籤與排版。只含水果的同題比較PNG依CC BY4.0；混合色字的第一張合成圖依前述BY-SA3.0，水果原素材仍依BY4.0。
- 英文：Thirdman，[Pexels原照片](https://www.pexels.com/photo/text-written-on-whiteboard-6503132/)，適用[Pexels License](https://www.pexels.com/license/)，不是公有領域。本包將其縮小為prepared/english.png作研究例圖，不放入兩張診斷合成圖；不表示作者背書，也不作stock/wallpaper再散布或商標用途。

原始照片未修改；prepared只作已記錄前處理，診斷框完全來自實際輸出，不生成、修補、美化或人工修正模型選取。圖片／raw檔是原件byte-exact副本，公開provenance JSON才是路徑轉換後衍生物。作者、原檔名、來源URL與限制完整保留在[sources](sources.json)，尺寸與input hash見[images](data/images.json)，模型框與raw/source-result hash見[figure provenance](assets/figures/provenance.json)。

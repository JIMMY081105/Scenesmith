from scripts.download_ambientcg import filter_downloads


def test_filter_downloads_skips_empty_filetype_category_lists() -> None:
    downloads = filter_downloads(
        assets=[
            {
                "assetId": "Ground102",
                "downloadFolders": {
                    "default": {
                        "downloadFiletypeCategories": [],
                    },
                },
            },
            {
                "assetId": "Wood095",
                "downloadFolders": {
                    "default": {
                        "downloadFiletypeCategories": {
                            "zip": {
                                "downloads": [
                                    {
                                        "attribute": "2K-PNG",
                                        "downloadLink": (
                                            "https://ambientcg.com/get?"
                                            "file=Wood095_2K-PNG.zip"
                                        ),
                                        "fileName": "Wood095_2K-PNG.zip",
                                        "size": 34016478,
                                    },
                                ],
                            },
                        },
                    },
                },
            },
        ],
        resolution="2K",
        file_format="PNG",
    )

    assert len(downloads) == 1
    assert downloads[0].asset_id == "Wood095"
    assert downloads[0].file_name == "Wood095_2K-PNG.zip"


def test_filter_downloads_handles_list_filetype_categories() -> None:
    downloads = filter_downloads(
        assets=[
            {
                "assetId": "Rock064",
                "downloadFolders": {
                    "default": {
                        "downloadFiletypeCategories": [
                            {
                                "title": "zip",
                                "downloads": [
                                    {
                                        "attribute": "2K-JPG",
                                        "downloadLink": (
                                            "https://ambientcg.com/get?"
                                            "file=Rock064_2K-JPG.zip"
                                        ),
                                        "fileName": "Rock064_2K-JPG.zip",
                                        "size": 28438777,
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        ],
        resolution="2K",
        file_format="JPG",
    )

    assert len(downloads) == 1
    assert downloads[0].asset_id == "Rock064"
    assert downloads[0].file_name == "Rock064_2K-JPG.zip"

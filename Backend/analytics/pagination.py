from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """{"count", "next", "previous", "results"} with ?page=&page_size= (default 50, max 1000)."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 1000

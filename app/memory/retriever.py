from app.memory.vector_store import retrieve_similar


class Retriever:

    def get_context(self, ticket_text: str):
        """
        Get similar past tickets
        """

        results = retrieve_similar(ticket_text)

        # 🔹 Handle empty / None safely
        if not results or "documents" not in results:
            return []

        documents = results.get("documents", [[]])

        if not documents or not documents[0]:
            return []

        return documents[0]

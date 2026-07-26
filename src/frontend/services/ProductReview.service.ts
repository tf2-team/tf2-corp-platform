// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import ProductReviewGateway from '../gateways/rpc/ProductReview.gateway';

const ProductReviewService = () => ({

    async getProductReviews(id: string) {
        const productReviews = await ProductReviewGateway.getProductReviews(id);

        return productReviews;
    },
    async getAverageProductReviewScore(id: string) {
        const averageScore = await ProductReviewGateway.getAverageProductReviewScore(id);

        return averageScore;
    },
    async askProductAIAssistant(id: string, question: string, userId: string) {
        // Returns a structured object: { status, answer, reason, claims }
        const response = await ProductReviewGateway.askProductAIAssistant(id, question, userId);

        return response;
    },
});

export default ProductReviewService();

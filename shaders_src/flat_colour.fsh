//
//  flat_colour.fsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

precision mediump float;

// Game uniforms
uniform lowp vec4 mu_FlatColour;

#ifdef GHOST_ALPHA_MODULATE
	uniform lowp float u_AlphaModulate;
#endif

void main()
{
	lowp vec4 fragColour = mu_FlatColour;
	
#ifdef GHOST_ALPHA_MODULATE
	fragColour.a *= -u_AlphaModulate;
#endif

	gl_FragColor = fragColour;
}

